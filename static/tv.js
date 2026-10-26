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
    let conversionWorker = null;
    let isConverting = false;

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

    function downloadBlob(blob, extension) {
        const link = document.createElement('a');
        const stamp = new Date().toISOString().replace(/[:.]/g, '-');
        link.href = URL.createObjectURL(blob);
        link.download = `rossiya-24-${stamp}.${extension}`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    }

    function floatToMonoPcm(audioBuffer) {
        const channels = Array.from(
            {length: audioBuffer.numberOfChannels},
            (_, index) => audioBuffer.getChannelData(index),
        );
        const pcm = new Int16Array(audioBuffer.length);
        for (let index = 0; index < audioBuffer.length; index += 1) {
            let sample = 0;
            channels.forEach((channel) => {
                sample += channel[index];
            });
            sample = Math.max(-1, Math.min(1, sample / channels.length));
            pcm[index] = sample < 0 ? sample * 32768 : sample * 32767;
        }
        return pcm;
    }

    async function convertToMp3(sourceBlob) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass || !window.Worker) {
            throw new Error('MP3 conversion is not supported');
        }

        isConverting = true;
        recordState.textContent = 'Конвертация в MP3';
        recordButton.disabled = true;
        recordStopButton.disabled = true;
        setMessage('Подготавливаем MP3… Не закрывайте страницу.');

        const audioContext = new AudioContextClass();
        let audioBuffer;
        try {
            audioBuffer = await audioContext.decodeAudioData(await sourceBlob.arrayBuffer());
        } finally {
            await audioContext.close();
        }
        const pcm = floatToMonoPcm(audioBuffer);

        return new Promise((resolve, reject) => {
            conversionWorker = new Worker(player.dataset.mp3WorkerUrl);
            conversionWorker.addEventListener('message', (event) => {
                if (event.data.type === 'progress') {
                    setMessage(`Конвертация в MP3: ${event.data.value}%`);
                    return;
                }
                if (event.data.type === 'complete') {
                    const blob = new Blob([event.data.buffer], {type: 'audio/mpeg'});
                    conversionWorker.terminate();
                    conversionWorker = null;
                    resolve(blob);
                    return;
                }
                if (event.data.type === 'error') {
                    conversionWorker.terminate();
                    conversionWorker = null;
                    reject(new Error(event.data.message));
                }
            });
            conversionWorker.addEventListener('error', (event) => {
                conversionWorker?.terminate();
                conversionWorker = null;
                reject(new Error(event.message || 'MP3 worker failed'));
            }, {once: true});
            conversionWorker.postMessage({
                samples: pcm.buffer,
                sampleRate: audioBuffer.sampleRate,
                bitRate: 128,
                encoderUrl: player.dataset.mp3EncoderUrl,
            }, [pcm.buffer]);
        });
    }

    async function downloadRecording() {
        if (!recordedChunks.length) return;
        const mimeType = mediaRecorder?.mimeType || 'audio/webm';
        const sourceBlob = new Blob(recordedChunks, {type: mimeType});

        if (mimeType.startsWith('audio/mpeg')) {
            downloadBlob(sourceBlob, 'mp3');
            setMessage('MP3 сохранён на устройство.');
            return;
        }

        try {
            const mp3Blob = await convertToMp3(sourceBlob);
            downloadBlob(mp3Blob, 'mp3');
            setMessage('MP3 сохранён на устройство.');
        } catch (error) {
            downloadBlob(sourceBlob, 'webm');
            setMessage('MP3 создать не удалось. Исходная запись сохранена в WebM.');
        }
    }

    function stopRecording(saveFile = true) {
        saveWhenStopped = saveFile;
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
        } else {
            stopTracks();
            if (!isConverting) resetRecorderUi();
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
            mediaRecorder.addEventListener('stop', async () => {
                stopTracks();
                try {
                    if (saveWhenStopped) await downloadRecording();
                } finally {
                    recordedChunks = [];
                    isConverting = false;
                    resetRecorderUi();
                }
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
        if (mediaRecorder?.state === 'recording' || isConverting) {
            stopRecording(false);
            event.preventDefault();
            event.returnValue = '';
        }
    });
    window.addEventListener('pagehide', () => {
        conversionWorker?.terminate();
        conversionWorker = null;
        stopRecording(false);
    });
    updateClocks();
    setInterval(updateClocks, 30000);
})();
