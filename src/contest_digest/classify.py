"""classify 단계: 전체 공모전 중 IT·데이터·AI 주제만 고른다.

1차: TypeSafe Jev(결정 모델, OpenRouter Decisions API)에 건별로 yes/no(noul) 질문을 던져 확률을 받는다.
2차: 확률이 애매한 구간이거나 Jev 호출이 실패한 건만 저가 LLM에 배치로 다시 묻는다.
3차: 그래도 답이 없으면 키워드 규칙.
IT 기술과 다른 분야(금융·경영·디자인 등) 지식이 함께 핵심인 융합·애매한 건은 both로 두어 두 트랙 모두에 보낸다.
목록 메타데이터(제목·주최·분야)만 쓰므로 상세 페이지·포스터 요청 전에 걸러진다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import requests

from .config import Settings
from .filters import is_it_related, is_mixed_related
from .llm import ModelCaps, chat_json
from .models import Listing

log = logging.getLogger(__name__)

IT_CRITERIA = {
    "instructions": "이 공모전의 주제가 IT·데이터·AI 분야인가? (참가자가 기술을 구현·분석·기획하는 것이 핵심인가)",
    "true": "AI/ML, AX(AI 전환), 데이터 분석, SW·앱·웹 개발, 해커톤, 보안, 디지털 서비스 기획처럼 기술이 공모의 핵심이다.",
    "false": "슬로건, 영상·사진, 디자인, 문학, 마케팅, 일반 창업처럼 기술이 핵심이 아니거나 AI 도구를 써서 창작물만 만드는 공모다.",
}

MIXED_CRITERIA = {
    "instructions": "이 공모전은 IT 기술과 다른 전문 분야가 융합되어, 컴퓨터공학 전공자만으로는 하기 어려운가?",
    "true": "AI·데이터를 도구로 쓰지만 금융·재무설계·경영·마케팅·디자인·정책 같은 비IT 전문 지식이나 산출물(보고서·기획서·작품)이 평가의 핵심이다. 예: AI 활용 재무설계 콘테스트.",
    "false": "기술 구현·분석이 핵심이고 다른 분야는 주제·소재일 뿐이다(예: 관광 서비스 해커톤), 또는 기술과 무관하다.",
}

PROMPT = f"""다음 공모전 목록에서 각 항목이 IT·데이터·AI 분야인지 판정하세요.

IT로 본다(is_it=true): {IT_CRITERIA["true"]}
IT가 아니다(is_it=false): {IT_CRITERIA["false"]}
제목만으로 애매하면 분야 태그와 주최를 참고하고, 그래도 애매하면 false로 둡니다.

mixed=true: {MIXED_CRITERIA["true"]} IT인지 아닌지 애매한 경우도 mixed=true로 둡니다.
mixed=false: {MIXED_CRITERIA["false"]}

모든 key에 대해 결과를 하나씩 반환하세요. reason은 15자 이내."""

SCHEMA = {
    "name": "classification",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["results"],
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["key", "is_it", "mixed", "reason"],
                    "properties": {"key": {"type": "string"}, "is_it": {"type": "boolean"},
                                   "mixed": {"type": "boolean"}, "reason": {"type": "string"}},
                },
            }
        },
    },
}


@dataclass
class Verdict:
    is_it: bool
    reason: str
    by: str  # 판정한 모델 ID 또는 "keyword"
    score: float | None = None  # Jev가 준 IT일 확률
    both: bool = False  # 융합·애매: IT·Non-IT 두 트랙 모두에 발송


def _state(it: Listing) -> dict:
    return {"title": it.title, "host": it.host, "categories": it.categories}


class JevDecider:
    """OpenRouter Decisions API 클라이언트 (chat/completions와 다른 엔드포인트)."""

    def __init__(self, settings: Settings, session=None):
        root = settings.openrouter_base_url.rstrip("/").removesuffix("/api/v1")
        self.url = f"{root}/api/alpha/decisions"
        self.model = settings.classifier_model
        self.key = settings.openrouter_api_key
        self.session = session or requests.Session()
        self.cost = 0.0

    def decide(self, listing: Listing) -> tuple[float, float]:
        """(IT일 확률, 융합 공모전일 확률)."""
        resp = self.session.post(
            self.url,
            headers={"Authorization": f"Bearer {self.key}"},
            json={
                "model": self.model,
                "state": _state(listing),
                "questions": {name: {
                    "type": "noul",
                    "instructions": c["instructions"],
                    "criteria": {"true": c["true"], "false": c["false"]},
                } for name, c in (("is_it", IT_CRITERIA), ("mixed", MIXED_CRITERIA))},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self.cost += float(data.get("usage", {}).get("cost") or 0)
        answers = data["answers"]
        return float(answers["is_it"]["noul"]), float(answers.get("mixed", {}).get("noul") or 0)


class Classifier:
    def __init__(self, settings: Settings, client=None, caps: ModelCaps | None = None, decider=None):
        self.settings = settings
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)
        self.client = client
        self.caps = caps or ModelCaps(settings.openrouter_base_url)
        self.decider = decider or JevDecider(settings)

    def _decide(self, listings: list[Listing]) -> tuple[dict[str, Verdict], list[Listing]]:
        """Jev 1차 판정. 확신 구간 밖(애매)이거나 실패한 건은 두 번째 값으로 돌려준다.

        IT 쪽이고 융합 확률이 높으면 both. 비IT로 확신해도 융합 확률이 높으면 2차 판정에 넘긴다.
        """
        lo, hi = self.settings.classify_low, self.settings.classify_high
        out, unsure = {}, []
        for it in listings:
            try:
                p, mixed = self.decider.decide(it)
            except Exception as exc:  # noqa: BLE001 - 2차 판정으로 넘긴다
                log.warning("Jev 판정 실패 %s: %s", it.key, exc)
                unsure.append(it)
                continue
            is_mixed = mixed >= self.settings.classify_mixed
            if p >= hi:
                out[it.key] = Verdict(True, f"p={p:.2f} mixed={mixed:.2f}", self.settings.classifier_model, p, is_mixed)
            elif p <= lo and not is_mixed:
                out[it.key] = Verdict(False, f"p={p:.2f}", self.settings.classifier_model, p)
            else:
                unsure.append(it)
        return out, unsure

    def _llm_batch(self, batch: list[Listing]) -> dict[str, Verdict]:
        model = self.settings.classifier_fallback_model
        rows = [{"key": it.key, **_state(it)} for it in batch]
        messages = [{"role": "user", "content": f"{PROMPT}\n\n[목록]\n{json.dumps(rows, ensure_ascii=False)}"}]
        data = chat_json(self.client, model, messages, SCHEMA, self.caps)
        keys = {it.key for it in batch}
        return {r["key"]: Verdict(bool(r["is_it"]) or bool(r.get("mixed")), r.get("reason", ""), model,
                                  both=bool(r.get("mixed")))
                for r in data.get("results", []) if r.get("key") in keys}

    def classify(self, listings: list[Listing]) -> dict[str, Verdict]:
        out, unsure = self._decide(listings)
        log.info("Jev 판정 %d건 (비용 $%.5f), 2차 판정 대상 %d건",
                 len(out), getattr(self.decider, "cost", 0.0), len(unsure))
        size = self.settings.classify_batch
        for i in range(0, len(unsure), size):
            batch = unsure[i:i + size]
            try:
                out.update(self._llm_batch(batch))
            except Exception as exc:  # noqa: BLE001
                log.warning("2차 분류 실패 (%s): %s", self.settings.classifier_fallback_model, exc)
            for it in batch:  # 2차에서도 답이 없으면 키워드 규칙
                out.setdefault(it.key, keyword_verdict(it))
        return out


def keyword_verdict(listing: Listing) -> Verdict:
    is_it = is_it_related(listing)
    return Verdict(is_it, "키워드 규칙", "keyword", both=is_it and is_mixed_related(listing))


def classify_by_keyword(listings: list[Listing]) -> dict[str, Verdict]:
    return {it.key: keyword_verdict(it) for it in listings}
