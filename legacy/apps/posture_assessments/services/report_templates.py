from copy import deepcopy


REPORT_TEMPLATES = {
    "low_back_pain": {
        "key": "low_back_pain",
        "label": "腰の負担タイプ",
        "short_title": "腰・骨盤まわりの負担を整えるプラン",
        "main_cause_title": "腰だけでなく骨盤・股関節の連動を確認します",
        "main_cause_text": (
            "腰まわりの負担は、骨盤の傾きや股関節の動き、"
            "体幹の支え方が重なって生じる可能性があります。"
            "施術者の評価と合わせて確認します。"
        ),
        "body_condition_points": [
            "骨盤の傾きと左右差の傾向を確認します。",
            "股関節と体幹が連動して動けているか確認します。",
            "座る・立つ・前かがみでの負担の変化を確認します。",
        ],
        "care_steps": [
            {
                "title": "Step1 腰への負担を整理",
                "text": "痛みや違和感が出やすい姿勢と動作を確認します。",
            },
            {
                "title": "Step2 骨盤・股関節ケア",
                "text": "骨盤まわりと股関節の動きやすさを整える方針を検討します。",
            },
            {
                "title": "Step3 体幹と日常動作",
                "text": "無理のない体幹運動と、腰に負担をためにくい動作を練習します。",
            },
        ],
        "home_care_examples": [
            "痛みのない範囲で、股関節まわりをゆっくり動かします。",
            "長時間同じ姿勢を避け、こまめに立ち上がります。",
            "腰を強く反らさず、呼吸を続けながら体幹を支えます。",
        ],
        "caution_text": (
            "強い痛みやしびれ、筋力低下がある場合は無理に運動せず、"
            "スタッフへ相談してください。"
        ),
        "patient_message": (
            "腰の状態は、骨盤や股関節の動きと一緒に整えることで、"
            "負担を減らせる可能性があります。無理のない段階から進めます。"
        ),
    },
    "knee_pain": {
        "key": "knee_pain",
        "label": "膝の負担タイプ",
        "short_title": "膝と下肢ラインを整えるプラン",
        "main_cause_title": "膝の向きと股関節・足部の連動を確認します",
        "main_cause_text": (
            "膝の負担は、膝だけでなく股関節の支え方や足部の向き、"
            "左右の荷重差が関係する可能性があります。"
        ),
        "body_condition_points": [
            "膝が内側・外側へ向きやすい傾向を確認します。",
            "股関節から膝、足部までのラインを確認します。",
            "立つ・歩く・階段での左右差を確認します。",
        ],
        "care_steps": [
            {
                "title": "Step1 膝の負担を確認",
                "text": "痛みが出る角度や動作、左右差を整理します。",
            },
            {
                "title": "Step2 股関節・足部を調整",
                "text": "膝を支える股関節と足部の動きやすさを確認します。",
            },
            {
                "title": "Step3 下肢の安定性づくり",
                "text": "膝の向きを保ちやすい立ち方や運動を段階的に行います。",
            },
        ],
        "home_care_examples": [
            "痛みのない範囲で、膝の曲げ伸ばしをゆっくり行います。",
            "立つときは膝とつま先の向きをそろえるよう意識します。",
            "強い屈伸や深いしゃがみ込みは無理に行わないでください。",
        ],
        "caution_text": (
            "腫れ、熱感、強い痛み、膝崩れがある場合は運動を控え、"
            "スタッフの確認を受けてください。"
        ),
        "patient_message": (
            "膝は股関節や足部と一緒に働いています。"
            "膝だけに負担を集めない動き方を、無理のない範囲で整えていきます。"
        ),
    },
    "neck_shoulder_pain": {
        "key": "neck_shoulder_pain",
        "label": "首・肩の負担タイプ",
        "short_title": "頭部位置と肩まわりを整えるプラン",
        "main_cause_title": "頭・首・肩甲帯の位置関係を確認します",
        "main_cause_text": (
            "頭が前へ出やすい姿勢や肩の左右差、胸郭の動きにより、"
            "首や肩へ負担が集まる可能性があります。"
        ),
        "body_condition_points": [
            "頭部前方位や首の傾きの傾向を確認します。",
            "肩の高さと肩甲骨位置の左右差を確認します。",
            "呼吸時の胸郭と背中の動きを確認します。",
        ],
        "care_steps": [
            {
                "title": "Step1 首・肩の負担を整理",
                "text": "姿勢や作業環境と症状の出方を確認します。",
            },
            {
                "title": "Step2 胸郭・肩甲帯ケア",
                "text": "胸まわりと肩甲骨が動きやすい状態を目指します。",
            },
            {
                "title": "Step3 頭部位置を支える",
                "text": "首へ力を入れすぎない姿勢と体幹の支え方を練習します。",
            },
        ],
        "home_care_examples": [
            "肩をすくめず、ゆっくり呼吸しながら胸を開きます。",
            "スマートフォンや画面の高さを見直します。",
            "首を強く回さず、肩甲骨を小さく動かします。",
        ],
        "caution_text": (
            "腕のしびれ、強い頭痛、めまい、筋力低下がある場合は、"
            "画像だけで判断せずスタッフへ相談してください。"
        ),
        "patient_message": (
            "首・肩の負担は、頭の位置や胸まわりの動きから整えることで、"
            "楽になる可能性があります。力を抜ける姿勢を一緒に探します。"
        ),
    },
    "posture_round_back": {
        "key": "posture_round_back",
        "label": "猫背・姿勢不良タイプ",
        "short_title": "胸郭と全身姿勢を整えるプラン",
        "main_cause_title": "背中の丸まりと体幹バランスを確認します",
        "main_cause_text": (
            "背中が丸まりやすい姿勢は、胸椎や肩甲骨の動き、"
            "骨盤位置、日常の座り姿勢が関係する可能性があります。"
        ),
        "body_condition_points": [
            "胸椎の丸まりと頭部位置の関係を確認します。",
            "肩甲骨と胸郭の動きやすさを確認します。",
            "骨盤から上半身までの重心位置を確認します。",
        ],
        "care_steps": [
            {
                "title": "Step1 姿勢習慣を確認",
                "text": "座り方や画面を見る時間など、姿勢が崩れやすい場面を整理します。",
            },
            {
                "title": "Step2 胸郭・背中を動かす",
                "text": "胸椎と肩甲骨を無理なく動かしやすい状態を目指します。",
            },
            {
                "title": "Step3 良い姿勢を保つ",
                "text": "力みすぎずに姿勢を支える呼吸と体幹運動を行います。",
            },
        ],
        "home_care_examples": [
            "背もたれに頼りすぎず、骨盤を立てやすい座り方を試します。",
            "深呼吸に合わせて胸をゆっくり広げます。",
            "30分から60分ごとに姿勢を変えます。",
        ],
        "caution_text": (
            "無理に胸を張り続けると腰や首へ負担が出る可能性があります。"
            "楽に続けられる範囲で行ってください。"
        ),
        "patient_message": (
            "姿勢は一度に固めるのではなく、動きやすさと支えやすさを"
            "少しずつ整えることが大切です。続けやすい方法から始めます。"
        ),
    },
    "sports_conditioning": {
        "key": "sports_conditioning",
        "label": "スポーツ動作タイプ",
        "short_title": "競技動作と全身連動を整えるプラン",
        "main_cause_title": "競技特有の動きと左右差を確認します",
        "main_cause_text": (
            "スポーツ時の負担は、競技動作の反復や左右差、"
            "体幹から手足への力の伝わり方が関係する可能性があります。"
        ),
        "body_condition_points": [
            "競技姿勢と通常姿勢の違いを確認します。",
            "体幹から上肢・下肢への連動を確認します。",
            "疲労時に崩れやすい動作や左右差を確認します。",
        ],
        "care_steps": [
            {
                "title": "Step1 競技動作を整理",
                "text": "症状が出るプレーやフォーム、練習量を確認します。",
            },
            {
                "title": "Step2 可動性と安定性",
                "text": "競技に必要な関節の動きと体幹の支え方を整えます。",
            },
            {
                "title": "Step3 段階的な復帰",
                "text": "強度を調整しながらフォームと再発予防を確認します。",
            },
        ],
        "home_care_examples": [
            "練習前後の体調と痛みの変化を記録します。",
            "競技で使う部位だけでなく全身を軽く動かします。",
            "強い疲労や痛みがある日は練習強度を調整します。",
        ],
        "caution_text": (
            "痛みを我慢した反復練習は負担を増やす可能性があります。"
            "復帰時期と運動量はスタッフと相談してください。"
        ),
        "patient_message": (
            "競技を続けるためには、痛む部位だけでなく全身の連動を"
            "確認することが大切です。目標に合わせて段階的に進めます。"
        ),
    },
    "elbow_wrist_pain": {
        "key": "elbow_wrist_pain",
        "label": "肘・手首の負担タイプ",
        "short_title": "上肢の使い方を整えるプラン",
        "main_cause_title": "肘・前腕・手首と肩の連動を確認します",
        "main_cause_text": (
            "肘や手首の負担は、前腕の使い方だけでなく、"
            "肩甲帯や体幹からの力の伝わり方が関係する可能性があります。"
        ),
        "body_condition_points": [
            "肘と手首を繰り返し使う動作を確認します。",
            "前腕の緊張と手首の向きを確認します。",
            "肩甲骨から腕への連動を確認します。",
        ],
        "care_steps": [
            {
                "title": "Step1 使用量を確認",
                "text": "仕事・家事・競技で負担が増える動作を整理します。",
            },
            {
                "title": "Step2 前腕・肩をケア",
                "text": "前腕だけでなく肩甲帯の動きやすさも確認します。",
            },
            {
                "title": "Step3 動作を再調整",
                "text": "手首へ力を集めすぎない持ち方やフォームを練習します。",
            },
        ],
        "home_care_examples": [
            "痛みのない範囲で手首と指をゆっくり動かします。",
            "強く握り続ける作業では、こまめに休憩します。",
            "前腕を強く伸ばしすぎず、軽い範囲でケアします。",
        ],
        "caution_text": (
            "腫れ、しびれ、握力低下、夜間の強い痛みがある場合は、"
            "無理に動かさずスタッフへ相談してください。"
        ),
        "patient_message": (
            "肘や手首は、肩や体幹からの動きとつながっています。"
            "使い方と休ませ方の両方を確認しながら整えていきます。"
        ),
    },
    "ankle_foot_pain": {
        "key": "ankle_foot_pain",
        "label": "足首・足部の負担タイプ",
        "short_title": "足元と荷重バランスを整えるプラン",
        "main_cause_title": "足首・足部と下肢ラインを確認します",
        "main_cause_text": (
            "足首や足部の負担は、足の向きやアーチ、"
            "膝・股関節との連動、左右の荷重差が関係する可能性があります。"
        ),
        "body_condition_points": [
            "足部の向きと左右の荷重差を確認します。",
            "足首から膝、股関節までのラインを確認します。",
            "立位・歩行時の踵とアーチの傾向を確認します。",
        ],
        "care_steps": [
            {
                "title": "Step1 足元の負担を確認",
                "text": "立つ・歩く・走る場面での痛みや違和感を整理します。",
            },
            {
                "title": "Step2 足首の動きを整える",
                "text": "足首と足趾を無理なく使える状態を目指します。",
            },
            {
                "title": "Step3 荷重バランスづくり",
                "text": "膝や股関節と連動した安定した立ち方を練習します。",
            },
        ],
        "home_care_examples": [
            "足指を軽く開閉し、足裏をゆっくり動かします。",
            "靴の減り方やサイズが合っているか確認します。",
            "痛みのない範囲で足首を小さく回します。",
        ],
        "caution_text": (
            "腫れ、強い痛み、体重をかけにくい状態がある場合は、"
            "無理に歩かずスタッフへ相談してください。"
        ),
        "patient_message": (
            "足元は全身を支える土台です。足首や足部だけでなく、"
            "膝や股関節とのつながりも確認しながら整えていきます。"
        ),
    },
    "general": {
        "key": "general",
        "label": "全身バランスタイプ",
        "short_title": "全身の姿勢バランスを整えるプラン",
        "main_cause_title": "一つの部位に限定せず全身のつながりを確認します",
        "main_cause_text": (
            "姿勢の特徴は、日常動作や左右差、複数の関節の動きが"
            "組み合わさって現れる可能性があります。"
            "施術者の評価と合わせて確認します。"
        ),
        "body_condition_points": [
            "頭部から足部までの全体バランスを確認します。",
            "左右差と前後の重心位置を確認します。",
            "日常動作で負担が集まりやすい場面を確認します。",
        ],
        "care_steps": [
            {
                "title": "Step1 状態を整理",
                "text": "姿勢、症状、日常動作を合わせて確認します。",
            },
            {
                "title": "Step2 動きやすさを整える",
                "text": "負担が集まりやすい部位と関連する関節をケアします。",
            },
            {
                "title": "Step3 良い状態を保つ",
                "text": "生活習慣と無理のない運動で再発予防を目指します。",
            },
        ],
        "home_care_examples": [
            "同じ姿勢が長く続かないよう、こまめに体を動かします。",
            "痛みのない範囲で深呼吸と軽い全身運動を行います。",
            "体調や違和感の変化を記録し、スタッフへ共有します。",
        ],
        "caution_text": (
            "痛みやしびれが強い場合は、画像や姿勢だけで判断せず、"
            "スタッフへ相談してください。"
        ),
        "patient_message": (
            "姿勢は日々の動きや体調によって変化します。"
            "無理なく続けられる方法を選び、少しずつ良い状態を目指します。"
        ),
    },
}


TEMPLATE_KEYWORDS = {
    "low_back_pain": {
        "腰痛": 5,
        "腰": 2,
        "腰椎": 3,
        "骨盤": 2,
        "股関節": 2,
    },
    "knee_pain": {
        "膝痛": 5,
        "膝": 3,
        "ニーイン": 4,
        "ニーアウト": 4,
        "下腿": 2,
        "足部": 1,
    },
    "neck_shoulder_pain": {
        "首肩": 5,
        "首": 3,
        "頚": 3,
        "肩": 2,
        "頭部前方": 4,
        "巻き肩": 4,
    },
    "posture_round_back": {
        "猫背": 5,
        "円背": 5,
        "背中": 2,
        "胸椎": 3,
        "姿勢不良": 4,
        "姿勢": 0.5,
    },
    "sports_conditioning": {
        "野球": 5,
        "バスケ": 5,
        "バスケット": 5,
        "サッカー": 5,
        "投球": 5,
        "スポーツ": 5,
        "競技": 4,
    },
    "elbow_wrist_pain": {
        "肘痛": 5,
        "肘": 3,
        "手首": 4,
        "前腕": 3,
    },
    "ankle_foot_pain": {
        "足首": 5,
        "足関節": 4,
        "足部": 3,
        "踵": 4,
        "アーチ": 4,
    },
}


def _flatten_text(value):
    if value is None:
        return []
    if isinstance(value, dict):
        items = []
        for item in value.values():
            items.extend(_flatten_text(item))
        return items
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            items.extend(_flatten_text(item))
        return items

    text = str(value).strip()
    return [text] if text else []


def _score_text(text, keywords):
    return sum(
        text.count(keyword) * weight
        for keyword, weight in keywords.items()
    )


def select_report_template(summary, assessment):
    summary = summary if isinstance(summary, dict) else {}
    memo = str(getattr(assessment, "memo", "") or "").strip()
    summary_values = [
        summary.get("important_points"),
        summary.get("overall_summary"),
        summary.get("posture_findings"),
        summary.get("suspected_load_areas"),
        summary.get("symptom_relation_hypotheses"),
        summary.get("joint_assessments"),
    ]
    summary_text = " ".join(
        text
        for value in summary_values
        for text in _flatten_text(value)
    )

    scores = {}
    for template_key, keywords in TEMPLATE_KEYWORDS.items():
        scores[template_key] = (
            _score_text(memo, keywords) * 3
            + _score_text(summary_text, keywords)
        )

    best_key = max(
        scores,
        key=lambda key: scores[key],
        default="general",
    )
    if scores.get(best_key, 0) < 1:
        best_key = "general"

    return deepcopy(REPORT_TEMPLATES[best_key])
