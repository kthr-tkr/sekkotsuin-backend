"""AI プロバイダー（OpenAI / 開発用の fake）。

患者の音声・写真を外部 API に送るため、利用は院の設定（ai_enabled）で ON/OFF できる。
"""

import base64
from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.core.config import settings


class Soap(BaseModel):
    S: list[str] = Field(description="主観: 患者の訴え・症状の経過")
    O: list[str] = Field(description="客観: 施術者が確認した所見・検査結果")  # noqa: E741
    A: list[str] = Field(description="評価: 施術者の見立て")
    P: list[str] = Field(description="計画: 施術方針・通院頻度・セルフケア指導")


class VisitSummary(BaseModel):
    soap: Soap
    chief_complaint: str = Field(description="主訴（短い一文）")
    onset: str = Field(description="いつから・きっかけ。不明なら空文字")
    pain_scale: int | None = Field(description="会話で言及された痛みの強さ 0〜10。不明なら null")
    red_flags: list[str] = Field(
        description="医療機関の受診を勧めるべき兆候（しびれの進行、発熱、外傷後の強い痛みなど）"
    )
    followups: list[str] = Field(description="次回の来院時に確認すること")


class PostureRegionsAi(BaseModel):
    head_neck: str
    shoulder: str
    spine: str
    pelvis: str
    hip: str
    knee: str
    ankle_foot: str
    balance: str


class PostureAiResult(BaseModel):
    overall_summary: str
    important_points: list[str]
    regions: PostureRegionsAi


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    audio_sec: int = 0


@dataclass
class Transcription:
    text: str
    usage: Usage


class AiProvider(Protocol):
    async def transcribe(self, data: bytes, filename: str, mime: str) -> Transcription: ...

    async def summarize_visit(
        self, transcript: str, context: str
    ) -> tuple[VisitSummary, Usage]: ...

    async def analyze_posture(
        self, images: list[tuple[str, bytes]], context: str
    ) -> tuple[PostureAiResult, Usage]: ...


SUMMARY_SYSTEM = """あなたは接骨院（柔道整復）の施術者を補助するアシスタントです。
施術中・問診中の会話の文字起こしから、カルテ用の SOAP 下書きを作ります。

- 会話に出てこない事実を作らないこと。不明な項目は空にする
- 病名の診断はしない。A（評価）は「〜の可能性」「〜の傾向」など施術者の見立てとして書く
- 各項目は簡潔な箇条書き（1項目 40 文字程度まで）
- 受診を勧めるべき兆候があれば red_flags に入れる
- 日本語で出力する"""

POSTURE_SYSTEM = """あなたは接骨院（柔道整復）の施術者を補助するアシスタントです。
患者の立位姿勢の写真（正面・側面・背面）から、施術者向けの姿勢所見の下書きを作ります。

- 写真から読み取れる傾向（頭部前方位、肩の高さの左右差、骨盤の傾き、膝の向きなど）を書く
- 角度などの数値は推測で断定しない。「やや」「傾向」などの表現にする
- 病名の診断はしない
- 写真に写っていない部位は空文字にする
- important_points は施術者が最初に確認すべき点を 3〜6 個
- 日本語で出力する"""


class OpenAiProvider:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def transcribe(self, data: bytes, filename: str, mime: str) -> Transcription:
        res = await self.client.audio.transcriptions.create(
            model=settings.openai_stt_model,
            file=(filename, data, mime),
            language="ja",
        )
        seconds = 0
        if res.usage is not None and res.usage.type == "duration":
            seconds = int(res.usage.seconds)
        return Transcription(
            text=res.text, usage=Usage(model=settings.openai_stt_model, audio_sec=seconds)
        )

    async def summarize_visit(self, transcript: str, context: str) -> tuple[VisitSummary, Usage]:
        res = await self.client.chat.completions.parse(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": f"{context}\n\n# 文字起こし\n{transcript}"},
            ],
            response_format=VisitSummary,
        )
        parsed = res.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("AI が要約を返しませんでした。")
        return parsed, _usage(settings.openai_model, res.usage)

    async def analyze_posture(
        self, images: list[tuple[str, bytes]], context: str
    ) -> tuple[PostureAiResult, Usage]:
        content: list[dict] = [{"type": "text", "text": context}]
        for label, jpeg in images:
            content.append({"type": "text", "text": f"# {label}"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
                        "detail": "high",
                    },
                }
            )
        res = await self.client.chat.completions.parse(
            model=settings.openai_vision_model,
            messages=[
                {"role": "system", "content": POSTURE_SYSTEM},
                {"role": "user", "content": content},  # type: ignore[list-item]
            ],
            response_format=PostureAiResult,
        )
        parsed = res.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("AI が分析結果を返しませんでした。")
        return parsed, _usage(settings.openai_vision_model, res.usage)


def _usage(model: str, usage: object | None) -> Usage:
    return Usage(
        model=model,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


class FakeProvider:
    """API キーなしで画面と処理の流れを確認するための固定応答。"""

    async def transcribe(self, data: bytes, filename: str, mime: str) -> Transcription:
        text = (
            "（開発用の文字起こし）先週から腰が痛くて、朝起きるときが一番つらいです。"
            "痛みは10段階で6くらい。前かがみで痛みが出ます。しびれはありません。"
        )
        return Transcription(text=text, usage=Usage(model="fake-stt"))

    async def summarize_visit(self, transcript: str, context: str) -> tuple[VisitSummary, Usage]:
        summary = VisitSummary(
            soap=Soap(
                S=["先週から腰痛", "起床時に痛みが強い", "しびれなし"],
                O=["前屈で腰部に疼痛"],
                A=["腰部の筋緊張による痛みの可能性"],
                P=["腰部の手技療法", "週2回の通院を提案"],
            ),
            chief_complaint="腰が痛い",
            onset="先週から",
            pain_scale=6,
            red_flags=[],
            followups=["起床時の痛みの変化"],
        )
        return summary, Usage(model="fake-llm", input_tokens=len(transcript), output_tokens=200)

    async def analyze_posture(
        self, images: list[tuple[str, bytes]], context: str
    ) -> tuple[PostureAiResult, Usage]:
        result = PostureAiResult(
            overall_summary="（開発用の分析結果）頭部前方位と右肩の下制傾向がみられます。",
            important_points=["頭部前方位", "右肩の下制", "骨盤の右下制傾向"],
            regions=PostureRegionsAi(
                head_neck="頭部がやや前方に位置する傾向",
                shoulder="右肩がやや低い",
                spine="",
                pelvis="右側がやや下制",
                hip="",
                knee="",
                ankle_foot="",
                balance="重心がやや右寄り",
            ),
        )
        return result, Usage(
            model="fake-vision", input_tokens=1000 * len(images), output_tokens=300
        )


class AiDisabledError(RuntimeError):
    pass


def get_provider() -> AiProvider:
    if settings.ai_provider == "openai":
        return OpenAiProvider()
    if settings.ai_provider == "fake":
        return FakeProvider()
    raise AiDisabledError("AI 機能は無効になっています。")


def estimate_cost_yen(usage: Usage) -> float:
    return round(
        usage.audio_sec / 60 * settings.ai_cost_yen_per_audio_minute
        + usage.input_tokens / 1000 * settings.ai_cost_yen_per_1k_input_tokens
        + usage.output_tokens / 1000 * settings.ai_cost_yen_per_1k_output_tokens,
        2,
    )
