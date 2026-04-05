import os
import json
from dataclasses import dataclass
from openai import OpenAI


@dataclass
class SoapResult:
    s: str
    o: str
    a: str
    p: str


SYSTEM_PROMPT = """
あなたは日本の接骨院（柔道整復）の保険請求を前提とした
カルテ作成を支援するアシスタントです。

入力は「問診（患者申告）」と「診察メモ（施術者メモ）」のみです。
出力は柔道整復のカルテ下書き（SOAP）です。

【最重要ルール（保険・返戻対策）】
- 医師の診断に該当する断定は禁止
  （骨折、脱臼、ヘルニア、神経根症、〇〇症確定 等）
- 評価は必ず「〜が示唆される」「〜の可能性が考えられる」表現にする
- S（主観）は患者の訴えのみ。「〜とのこと」「〜と訴える」を用いる
- O（客観）は施術者の観察・検査結果のみ
- 不明な項目は無理に補完せず「不明」「確認中」と記載
- 個人情報（氏名・住所・電話番号など）は記載しない
- 長文は禁止。箇条書き・簡潔な短文を優先
- 出力は必ず JSON 形式で、キーは s, o, a, p のみ
- 重要：JSONの各値(s,o,a,p)は必ず文字列(string)。入れ子のdict/listは禁止。

【SOAP 記載方針（柔整用）】
S（主観）：
- 主訴
- 発症時期・きっかけ（患者申告）
- 増悪因子・軽減因子
- 日常生活動作への支障
※ 患者の言葉として表現する

O（客観）：
- 視診・触診・圧痛
- 可動域制限
- 疼痛誘発動作
- 腫脹・熱感の有無
※ 実施していない検査は「未実施」「不明」と記載

A（評価）：
- 訴えおよび所見を踏まえた状態の評価
- 断定せず、可能性・示唆表現を用いる
- 注意すべき症状や、医科受診を検討する条件があれば記載

P（計画）：
- 実施した施術内容（簡潔）
- 日常生活上の注意・セルフケア指導
- 次回来院の目安（例：数日〜1週間程度）
- 経過により対応を検討する旨
""".strip()


USER_PROMPT_TEMPLATE = """
【問診（患者申告）】
{intake_text}

【診察メモ（施術者メモ）】
{exam_text}

上記の情報のみを根拠として、
柔道整復の保険請求を想定したカルテ下書き（SOAP）を作成してください。

出力は JSON（s,o,a,p）で返してください。
注意：JSONの各値(s,o,a,p)は必ず文字列(string)で、入れ子のdict/listは禁止です。
""".strip()


def _client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY が未設定です（.env / 環境変数を確認）")
    return OpenAI(api_key=api_key)


def _to_text(v) -> str:
    """
    OpenAIがたまに dict/list を返す事故対策：
    どんな型でも最終的に必ず文字列に寄せる。
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (dict, list)):
        # 監査・デバッグで見やすいよう JSON化して残す
        return json.dumps(v, ensure_ascii=False, indent=2).strip()
    return str(v).strip()


def generate_soap_openai(intake_text: str, exam_text: str, model: str) -> SoapResult:
    client = _client()

    user_prompt = USER_PROMPT_TEMPLATE.format(
        intake_text=(intake_text or "").strip(),
        exam_text=(exam_text or "").strip(),
    )

    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )

    data = json.loads(resp.choices[0].message.content)

    return SoapResult(
        s=_to_text(data.get("s", "")),
        o=_to_text(data.get("o", "")),
        a=_to_text(data.get("a", "")),
        p=_to_text(data.get("p", "")),
    )
