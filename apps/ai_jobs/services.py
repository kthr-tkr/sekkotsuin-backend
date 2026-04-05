from dataclasses import dataclass

@dataclass
class SoapResult:
    s: str
    o: str
    a: str
    p: str


def generate_soap_stub(intake_text: str, exam_text: str) -> SoapResult:
    """
    まずは動作確認用のダミー（後でOpenAIに差し替え）
    """
    s = f"【主訴】\n{intake_text}\n\n【診察メモ】\n{exam_text}".strip()
    o = "【所見】\n圧痛・可動域・腫脹などを確認。"
    a = "【評価】\n訴えおよび所見から、患部に負担がかかり疼痛が出現している状態と考えられる。"
    p = "【施術】\n手技療法を中心に実施。\n【指導】\n日常生活動作の注意点を説明。\n【方針】\n経過観察し必要に応じて継続施術。"
    return SoapResult(s=s, o=o, a=a, p=p)
