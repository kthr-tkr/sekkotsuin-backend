(() => {
  const S = window.AI_INTERVIEW || {};
  const $ = (q) => document.querySelector(q);
  const $$ = (q) => document.querySelectorAll(q);

  // ===== tabs =====
  const panes = {
    input: $("#tab-input"),
    processing: $("#tab-processing"),
    visual: $("#tab-visual"),
  };

  function setProgress(tab) {
    const bar = $("#progressBar");
    if (!bar) return;
    bar.style.width = tab === "input" ? "33%" : tab === "processing" ? "66%" : "100%";
  }

  function switchTab(tab) {
    $$(".tab").forEach(t => t.classList.remove("active"));
    document.querySelector(`.tab[data-tab="${tab}"]`)?.classList.add("active");
    Object.keys(panes).forEach(k => panes[k].style.display = (k === tab ? "" : "none"));
    setProgress(tab);
  }

  // tabs click
  $$(".tab").forEach(t => t.addEventListener("click", () => switchTab(t.dataset.tab)));

  // quick buttons
  $("#btnGoVisual")?.addEventListener("click", () => switchTab("visual"));
  $("#btnGoVisual2")?.addEventListener("click", () => switchTab("visual"));
  $("#btnGoInput")?.addEventListener("click", () => switchTab("input"));
  $("#btnBackProcessing")?.addEventListener("click", () => switchTab("processing"));

  // ===== input segment =====
  function switchInput(mode) {
    $("#input-audio").style.display = mode === "audio" ? "" : "none";
    $("#input-manual").style.display = mode === "manual" ? "" : "none";
    $("#input-paste").style.display = mode === "paste" ? "" : "none";
    const hint = $("#inputHint");
    if (!hint) return;
    hint.textContent =
      mode === "audio"
        ? "マイクボタンをクリックして問診を録音します。AI音声認識により自動的にテキスト化し、施術者の判断を支援します。"
        : mode === "manual"
        ? "施術者のメモを直接入力できます。入力内容は文字起こしと同じ扱いで解析に回せます。"
        : "外部テキストを貼り付けて保存できます。過去カルテの要点などもOKです。";
  }

  $$(".seg button[data-input]").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".seg button[data-input]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      switchInput(btn.dataset.input);
    });
  });

  // ===== recording (MediaRecorder) =====
  let mediaRecorder = null;
  let chunks = [];
  let recordedBlob = null;
  let timerInt = null;
  let sec = 0;

  const micBtn = $("#micBtn");
  const timer = $("#timer");
  const recordState = $("#recordState");
  const btnUpload = $("#btnUpload");
  const btnRetry = $("#btnRetry");
  const audioMeta = $("#audioMeta");

  function fmtTime(s) {
    const mm = String(Math.floor(s / 60)).padStart(2, "0");
    const ss = String(s % 60).padStart(2, "0");
    return `${mm}:${ss}`;
  }

  function startTimer() {
    sec = 0;
    timer.textContent = "00:00";
    timerInt = setInterval(() => {
      sec += 1;
      timer.textContent = fmtTime(sec);
    }, 1000);
  }
  function stopTimer() {
    if (timerInt) clearInterval(timerInt);
    timerInt = null;
  }

  async function startRecording() {
    recordedBlob = null;
    chunks = [];
    btnUpload.disabled = true;
    btnRetry.style.display = "none";

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeCandidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg",
      "audio/mp4",
      "audio/wav",
    ];
    const mimeType = mimeCandidates.find(m => MediaRecorder.isTypeSupported(m)) || "";

    mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);

    mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    mediaRecorder.onstop = () => {
      stopTimer();
      recordedBlob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
      const kb = Math.round(recordedBlob.size / 1024);
      audioMeta.textContent = `録音: ${fmtTime(sec)} / ${kb}KB / ${recordedBlob.type || "unknown"}`;
      $("#transcriptPreview").textContent = "（アップロード後にここへ文字起こし結果が表示されます）";
      btnUpload.disabled = false;
      btnRetry.style.display = "";
      recordState.textContent = "録音完了（アップロードできます）";
    };

    mediaRecorder.start();
    micBtn.classList.add("recording");
    recordState.textContent = "RECORDING... CLICK TO STOP";
    startTimer();
  }

  function stopRecording() {
    if (!mediaRecorder) return;
    mediaRecorder.stop();
    // stop mic
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
    micBtn.classList.remove("recording");
  }

  micBtn?.addEventListener("click", async () => {
    try {
      if (!mediaRecorder || mediaRecorder.state === "inactive") {
        await startRecording();
      } else if (mediaRecorder.state === "recording") {
        stopRecording();
      }
    } catch (e) {
      alert("マイクの使用が許可されていません。ブラウザの権限設定を確認してください。");
      console.error(e);
    }
  });

  btnRetry?.addEventListener("click", () => {
    recordedBlob = null;
    chunks = [];
    btnUpload.disabled = true;
    btnRetry.style.display = "none";
    audioMeta.textContent = "";
    $("#transcriptPreview").textContent = "（まだありません）";
    timer.textContent = "00:00";
    recordState.textContent = "CLICK TO START RECORDING";
  });

  // ===== upload =====
  btnUpload?.addEventListener("click", async () => {
    if (!recordedBlob) return;

    // 実URLがrecording_id=0 の場合は、あなた側でURL調整してください（recording作成後に差し替え）
    const url = S.uploadUrl;
    if (!url || url.endsWith("/0/")) {
      alert("uploadUrl の recording_id が未設定です（テンプレのURL名を確認してください）");
      return;
    }

    const fd = new FormData();
    const ext = recordedBlob.type.includes("ogg") ? "ogg" : "webm";
    fd.append("audio", recordedBlob, `recording.${ext}`);
    fd.append("duration_sec", String(sec));
    fd.append("mime_type", recordedBlob.type || "");

    btnUpload.disabled = true;
    recordState.textContent = "アップロード中…";

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": S.csrfToken },
        body: fd,
      });

      if (!res.ok) throw new Error("upload failed");
      const data = await res.json().catch(() => ({}));

      recordState.textContent = "アップロード完了。処理へ進めます。";
      switchTab("processing");

      // ここでサーバが transcript_text を返したら表示（任意）
      if (data.transcript_text) {
        $("#transcriptPreview").textContent = data.transcript_text;
        $("#transcriptBox").textContent = data.transcript_text;
      }
    } catch (e) {
      console.error(e);
      recordState.textContent = "アップロードに失敗しました";
      btnUpload.disabled = false;
      alert("アップロードに失敗しました。サーバログを確認してください。");
    }
  });

  // ===== copy transcript =====
  $("#btnCopyTranscript")?.addEventListener("click", async () => {
    const t = $("#transcriptBox")?.textContent || "";
    if (!t.trim()) return;
    await navigator.clipboard.writeText(t);
    alert("コピーしました");
  });

  // ===== render summary_json into VISUAL =====
  function safeGet(obj, path, fallback = null) {
    try {
      return path.split(".").reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), obj) ?? fallback;
    } catch {
      return fallback;
    }
  }

  function renderVisual(summary) {
    const locList = $("#locList");
    const locCount = $("#locCount");
    const soapBox = $("#soapBox");

    if (!locList || !locCount || !soapBox) return;

    const locs = safeGet(summary, "structured.locations", []) || [];
    locCount.textContent = String(locs.length);

    locList.innerHTML = "";
    if (!locs.length) {
      locList.innerHTML = `<div class="muted">（患部情報がまだありません）</div>`;
    } else {
      for (const l of locs) {
        const label = l.label || l.code || "不明";
        const sev = l.severity ?? "-";
        const quality = l.quality || "";
        const note = l.note || "";
        const trigger = l.trigger || "";
        locList.insertAdjacentHTML("beforeend", `
          <div class="loc-item">
            <div>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                <div style="font-weight:900;color:#111827;">${label}</div>
                ${quality ? `<span class="badge">${quality}</span>` : ``}
                ${trigger ? `<span class="badge">きっかけ: ${trigger}</span>` : ``}
              </div>
              <div class="muted" style="margin-top:6px;white-space:pre-wrap;">${note}</div>
            </div>
            <div class="badge"><span class="score">${sev}</span>/10</div>
          </div>
        `);
      }
    }

    const soap = safeGet(summary, "soap", null);
    if (!soap) {
      soapBox.textContent = "（まだありません）";
    } else {
      soapBox.innerHTML = `
        <div class="kvs">
          <div class="kv"><div class="k">S</div><div class="v">${(soap.S || "").replaceAll("\n","<br>")}</div></div>
          <div class="kv"><div class="k">O</div><div class="v">${(soap.O || "").replaceAll("\n","<br>")}</div></div>
          <div class="kv"><div class="k">A</div><div class="v">${(soap.A || "").replaceAll("\n","<br>")}</div></div>
          <div class="kv"><div class="k">P</div><div class="v">${(soap.P || "").replaceAll("\n","<br>")}</div></div>
        </div>
      `;
    }
  }

  // patient mode toggle (UIのみ：内容切替は summary_json.patient_friendly を入れたら差し替え可能)
  $("#patientMode")?.addEventListener("change", (e) => {
    // ここは後で「患者向け要約」を表示する切替にする
    // 今は表示のまま
  });

  // 初期描画
  if (S.summaryJson) {
    try {
      // summary_json が dict の場合はそのまま、文字列の場合はparse
      const summary = (typeof S.summaryJson === "string") ? JSON.parse(S.summaryJson) : S.summaryJson;
      renderVisual(summary);
    } catch (e) {
      console.warn("summary_json parse error", e);
    }
  }

  // 保存（手入力/貼付）→ transcript_textとして扱う（APIが未ならアラート）
  function notImplementedYet() {
    alert("この保存処理はまだサーバ側APIが必要です。まずは録音→アップロードフローを完成させましょう。");
  }
  $("#btnSaveManual")?.addEventListener("click", notImplementedYet);
  $("#btnSavePaste")?.addEventListener("click", notImplementedYet);

  // export（仮）
  $("#btnExport")?.addEventListener("click", () => {
    alert("カルテ反映は次のステップ（Inspection/Chart連携）で実装します。");
  });
})();
