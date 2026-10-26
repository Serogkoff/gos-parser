(() => {
    'use strict';

    const player = document.getElementById('tv-player');
    const frame = document.getElementById('tv-frame');
    const placeholder = document.getElementById('tv-placeholder');
    const playButton = document.getElementById('tv-play');
    const stopButton = document.getElementById('tv-stop');
    const recordButton = document.getElementById('record-start');
    const recordStopButton = document.getElementById('record-stop');
    const recordState = document.getElementById('record-state');
    const recordTime = document.getElementById('record-time');
    const message = document.getElementById('tv-message');
    let captureStream = null;
    let mediaRecorder = null;
    let recordedChunks = [];
    let timer = null;
    let startedAt = 0;
    let saveWhenStopped = false;

    function updateClocks() {
        document.querySelectorAll('[data-clock]').forEach((clock) => {
            clock.textContent = new Intl.DateTimeFormat('ru-RU', {
                timeZone: clock.dataset.clock,
                hour: '2-digit',
                minute: '2-digit',
            }).format(new Date());
        });
    }

    function setMessage(value) {
        message.textContent = value || '';
    }

    function updateTimer() {
        const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
        const minutes = String(Math.floor(seconds / 60)).padStart(2, '0');
        recordTime.textContent = `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
    }

    function stopTracks() {
        if (captureStream) captureStream.getTracks().forEach((track) => track.stop());
        captureStream = null;
    }

    function resetRecorderUi() {
        clearInterval(timer);
        timer = null;
        recordState.textContent = 'Не запущена';
        recordButton.disabled = false;
        recordButton.classList.remove('recording');
        recordStopButton.disabled = true;
    }

    function downloadRecording() {
        if (!recordedChunks.length) return;
        const mimeType = mediaRecorder?.mimeType || 'audio/webm';
        const blob = new Blob(recordedChunks, {type: mimeType});
        const link = document.createElement('a');
        const stamp = new Date().toISOString().replace(/[:.]/g, '-');
        link.href = URL.createObjectURL(blob);
        link.download = `rossiya-24-${stamp}.webm`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        setMessage('Запись сохранена на устройство.');
    }

    function stopRecording(saveFile = true) {
        saveWhenStopped = saveFile;
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
        } else {
            stopTracks();
            resetRecorderUi();
        }
    }

    playButton.addEventListener('click', () => {
        if (!frame.src) frame.src = player.dataset.streamSrc;
        frame.hidden = false;
        placeholder.hidden = true;
        playButton.disabled = true;
        stopButton.disabled = false;
        setMessage('');
    });

    stopButton.addEventListener('click', () => {
        stopRecording(true);
        frame.src = 'about:blank';
        frame.hidden = true;
        placeholder.hidden = false;
        playButton.disabled = false;
        stopButton.disabled = true;
    });

    recordButton.addEventListener('click', async () => {
        setMessage('');
        if (!navigator.mediaDevices?.getDisplayMedia || !window.MediaRecorder) {
            setMessage('Этот браузер не поддерживает запись звука вкладки.');
            return;
        }
        try {
            captureStream = await navigator.mediaDevices.getDisplayMedia({
                video: true,
                audio: true,
            });
            const audioTracks = captureStream.getAudioTracks();
            if (!audioTracks.length) {
                stopTracks();
                setMessage('Звук вкладки не передан. Повторите и включите «Передавать звук вкладки».');
                return;
            }
            const audioStream = new MediaStream(audioTracks);
            const preferredTypes = ['audio/webm;codecs=opus', 'audio/webm', 'video/webm;codecs=opus'];
            const mimeType = preferredTypes.find((type) => MediaRecorder.isTypeSupported(type)) || '';
            mediaRecorder = new MediaRecorder(audioStream, mimeType ? {mimeType} : undefined);
            recordedChunks = [];
            saveWhenStopped = false;
            mediaRecorder.addEventListener('dataavailable', (event) => {
                if (event.data.size) recordedChunks.push(event.data);
            });
            mediaRecorder.addEventListener('stop', () => {
                stopTracks();
                if (saveWhenStopped) downloadRecording();
                recordedChunks = [];
                resetRecorderUi();
            }, {once: true});
            captureStream.getTracks().forEach((track) => track.addEventListener('ended', () => stopRecording(true), {once: true}));
            mediaRecorder.start(1000);
            startedAt = Date.now();
            updateTimer();
            timer = setInterval(updateTimer, 1000);
            recordState.textContent = 'Идёт запись';
            recordButton.disabled = true;
            recordButton.classList.add('recording');
            recordStopButton.disabled = false;
            setMessage('Идёт запись звука выбранной вкладки.');
        } catch (error) {
            stopTracks();
            resetRecorderUi();
            if (error?.name !== 'NotAllowedError') setMessage('Не удалось начать запись. Проверьте разрешение браузера.');
        }
    });

    recordStopButton.addEventListener('click', () => stopRecording(true));
    window.addEventListener('beforeunload', (event) => {
        if (mediaRecorder?.state === 'recording') {
            stopRecording(false);
            event.preventDefault();
            event.returnValue = '';
        }
    });
    window.addEventListener('pagehide', () => stopRecording(false));
    updateClocks();
    setInterval(updateClocks, 30000);
})();
