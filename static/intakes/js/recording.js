// static/intakes/js/recording.js
(() => {
  const wrap = document.querySelector(".ai-wrap");
  if (!wrap) return;

  const uploadUrl = wrap.dataset.uploadUrl;
  const processUrl = wrap.dataset.processUrl;
  const detailUrl = wrap.dataset.detailUrl;
  const csrfToken = wrap.dataset.csrf;

  const recBtn = document.getElementById("recBtn");
  const recIcon = document.getElementById("recIcon");
  const recState = document.getElementById("recState");
  const timerEl = document.getElementById("timer");
  const uploadState = document.getElementById("uploadState");
  const audioPreview = document.getElementById("audioPreview");
  const goDetailBtn = document.getElementById("goDetailBtn");

  let mediaRecorder = null;
  let stream = null;
  let chunks = [];
  let recording = false;
  let t0 = 0;
  let timerId = null;

  const pad2 = (n) => String(n).padStart(2, "0");
  const formatTime = (sec) => `${pad2(Math.floor(sec / 60))}:${pad2(sec % 60)}`;

  function setUIIdle() {
    recording = false;
    recBtn.classList.remove("is-recording");
    recIcon.textContent = "🎙️";
    recState.textContent = "CLICK TO START RECORDING";
    clearInterval(timerId);
    timerId = null;
  }

  function setUIRecording() {
    recording = true;
    recBtn.classList.add("is-recording");
    recIcon.textContent = "⏹️";
    recState.textContent = "RECORDING...";
  }

  function setUploadState(msg, kind = "") {
    uploadState.textContent = msg || "";
    uploadState.className = "upload-state" + (kind ? ` ${kind}` : "");
  }

  function startTimer() {
    t0 = Date.now();
    timerEl.textContent = "00:00";
    clearInterval(timerId);
    timerId = setInterval(() => {
      const sec = Math.floor((Date.now() - t0) / 1000);
      timerEl.textContent = formatTime(sec);
    }, 250);
  }

  async function startRec() {
    setUploadState("");
    goDetailBtn.style.display = "none";

    // 既存streamがあれば終了
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (e) {
      setUploadState("マイクの許可が必要です。ブラウザ設定を確認してください。", "error");
      setUIIdle();
      return;
    }

    chunks = [];

    // mimeType は環境で差があるので、使えるものを選ぶ
    const preferred = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg",
    ];
    const mimeType = preferred.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";

    try {
      mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    } catch (e) {
      setUploadState("このブラウザでは録音がサポートされていない可能性があります。", "error");
      setUIIdle();
      return;
    }

    mediaRecorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunks.push(ev.data);
    };

    mediaRecorder.onstop = async () => {
      clearInterval(timerId);
      timerId = null;

      const durationSec = Math.max(0, Math.round((Date.now() - t0) / 1000));

      const blobType = mediaRecorder.mimeType || "audio/webm";
      const blob = new Blob(chunks, { type: blobType });

      // ✅ 無音/失敗の簡易判定（サイズが極端に小さい）
      if (blob.size < 5000) {
        setUploadState("録音データが小さすぎます（無音の可能性）。もう一度録音してください。", "error");
        setUIIdle();
        return;
      }

      // プレビュー表示
      const url = URL.createObjectURL(blob);
      audioPreview.src = url;
      audioPreview.style.display = "block";

      setUploadState("アップロード中...", "loading");

      // ✅ 拡張子を付ける（重要）
      const ext = blobType.includes("ogg") ? "ogg" : "webm";
      const file = new File([blob], `recording_${Date.now()}.${ext}`, { type: blobType });

      const fd = new FormData();
      fd.append("audio", file);
      fd.append("duration_sec", String(durationSec));

      try {
        const res = await fetch(uploadUrl, {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken },
          body: fd,
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          throw new Error(data.error || `upload failed: ${res.status}`);
        }

        setUploadState("アップロード完了。", "ok");
        goDetailBtn.style.display = "inline-flex";
        goDetailBtn.href = detailUrl;

      } catch (e) {
        setUploadState(`アップロードに失敗しました：${e.message}`, "error");
      } finally {
        setUIIdle();
      }
    };

    // 開始
    setUIRecording();
    startTimer();
    mediaRecorder.start();
  }

  function stopRec() {
    try {
      if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
      }
      // streamはonstop後に止めたいが、環境によっては即止めてもOK
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
        stream = null;
      }
    } catch (e) {
      setUploadState("停止に失敗しました。もう一度お試しください。", "error");
      setUIIdle();
    }
  }

  // ボタンでトグル
  recBtn?.addEventListener("click", () => {
    if (!recording) startRec();
    else stopRec();
  });

  // 初期状態
  setUIIdle();
})();