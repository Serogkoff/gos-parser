(() => {
    'use strict';

    const player = document.getElementById('tv-player');
    const frame = document.getElementById('tv-frame');
    const video = document.getElementById('tv-video');
    const placeholder = document.getElementById('tv-placeholder');
    const placeholderTitle = document.getElementById('tv-placeholder-title');
    const placeholderCopy = document.getElementById('tv-placeholder-copy');
    const playButton = document.getElementById('tv-play');
    const playLabel = document.getElementById('tv-play-label');
    const channelButtons = Array.from(document.querySelectorAll('[data-tv-channel]'));
    const sourceLink = document.getElementById('tv-source-link');
    const recordButton = document.getElementById('record-start');
    const recordState = document.getElementById('record-state');
    const recordTime = document.getElementById('record-time');
    const message = document.getElementById('tv-message');

    let activeChannel = channelButtons.find((button) => button.classList.contains('active')) || channelButtons[0];
    let activePlayerKind = '';
    let hls = null;
    let captureStream = null;
    let mediaRecorder = null;
    let recordedChunks = [];
    let timer = null;
    let startedAt = 0;
    let saveWhenStopped = false;
    let conversionWorker = null;
    let isConverting = false;
    let recordingSlug = 'tv';

    function updateClocks() {
        document.querySelectorAll('[data-clock]').forEach((clock) => {
            const now = new Date();
            const time = clock.querySelector('.tv-clock-time');
            const date = clock.querySelector('.tv-clock-date');
            if (time) {
                time.textContent = new Intl.DateTimeFormat('ru-RU', {
                    timeZone: clock.dataset.clock,
                    hour: '2-digit',
                    minute: '2-digit',
                }).format(now);
            }
            if (date) {
                date.textContent = new Intl.DateTimeFormat('ru-RU', {
                    timeZone: clock.dataset.clock,
                    day: '2-digit',
                    month: '2-digit',
                    year: 'numeric',
                }).format(now);
            }
        });
    }

    function setMessage(value) {
        message.textContent = value || '';
    }

    function setPlaceholder(title, copy) {
        placeholderTitle.textContent = title || '';
        placeholderTitle.hidden = !title;
        placeholderCopy.textContent = copy || '';
        placeholderCopy.hidden = !copy;
        placeholder.hidden = false;
    }

    function setStreamButton(label, {disabled = false, running = false} = {}) {
        playLabel.textContent = label;
        playButton.disabled = disabled;
        playButton.setAttribute('aria-pressed', running ? 'true' : 'false');
        player.classList.toggle('is-running', running);
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
        recordState.textContent = 'Запись остановлена';
        recordButton.textContent = '● Начать запись';
        recordButton.disabled = false;
        recordButton.classList.remove('recording');
        recordButton.setAttribute('aria-pressed', 'false');
    }

    function slugForChannel() {
        return activeChannel?.dataset.tvChannel === 'mid' ? 'mid-russia' : 'rossiya-24';
    }

    function downloadBlob(blob, extension) {
        const link = document.createElement('a');
        const stamp = new Date().toISOString().replace(/[:.]/g, '-');
        link.href = URL.createObjectURL(blob);
        link.download = `${recordingSlug}-${stamp}.${extension}`;
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
        recordButton.textContent = 'Подготавливаем MP3…';
        recordButton.disabled = true;
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
            recordButton.disabled = true;
            recordButton.textContent = saveFile ? 'Сохраняем…' : 'Останавливаем…';
            mediaRecorder.stop();
        } else {
            stopTracks();
            if (!isConverting) resetRecorderUi();
        }
    }

    function destroyHlsPlayer() {
        if (hls) {
            hls.destroy();
            hls = null;
        }
        video.pause();
        video.removeAttribute('src');
        video.load();
        video.hidden = true;
    }

    function resetPlayer({saveRecording = true} = {}) {
        if (mediaRecorder?.state === 'recording') stopRecording(saveRecording);
        frame.src = 'about:blank';
        frame.hidden = true;
        destroyHlsPlayer();
        activePlayerKind = '';
        setPlaceholder('', '');
        setStreamButton('Запустить эфир');
    }

    function markPlayerStarted(kind) {
        activePlayerKind = kind;
        placeholder.hidden = true;
        setStreamButton('Остановить эфир', {running: true});
    }

    async function playMidStream() {
        setStreamButton('Проверяем эфир…', {disabled: true});
        setPlaceholder('', '');
        setMessage('');

        let response;
        let payload;
        try {
            response = await fetch(activeChannel.dataset.discoveryUrl, {
                credentials: 'same-origin',
                headers: {'Accept': 'application/json'},
            });
            payload = await response.json();
        } catch (error) {
            payload = {available: false, reason: 'unavailable', title: 'Не удалось проверить трансляцию'};
        }

        if (!response?.ok || !payload.available || !payload.stream_url) {
            setPlaceholder(
                payload.title || 'Сейчас трансляции нет',
                payload.reason === 'unavailable'
                    ? 'Источник временно не ответил. Можно открыть официальный видеораздел.'
                    : 'Когда МИД начнёт эфир, он появится здесь после повторной проверки.',
            );
            setStreamButton('Проверить снова');
            sourceLink.href = payload.external_url || activeChannel.dataset.sourceUrl;
            return;
        }

        sourceLink.href = payload.external_url || activeChannel.dataset.sourceUrl;
        video.hidden = false;
        placeholder.hidden = true;

        const streamUrl = payload.stream_url;
        if (video.canPlayType('application/vnd.apple.mpegurl')) {
            video.src = streamUrl;
            markPlayerStarted('hls');
            try {
                await video.play();
            } catch (error) {
                setMessage('Поток готов. Нажмите Play внутри плеера.');
            }
            return;
        }

        if (window.Hls?.isSupported()) {
            hls = new window.Hls({
                enableWorker: true,
                lowLatencyMode: true,
                backBufferLength: 30,
                maxBufferLength: 20,
            });
            hls.on(window.Hls.Events.MEDIA_ATTACHED, () => hls.loadSource(streamUrl));
            hls.on(window.Hls.Events.MANIFEST_PARSED, async () => {
                try {
                    await video.play();
                } catch (error) {
                    setMessage('Поток готов. Нажмите Play внутри плеера.');
                }
            });
            hls.on(window.Hls.Events.ERROR, (_event, data) => {
                if (!data.fatal) return;
                if (data.type === window.Hls.ErrorTypes.NETWORK_ERROR) {
                    hls.startLoad();
                    setMessage('Связь с эфиром прервалась — переподключаемся…');
                } else if (data.type === window.Hls.ErrorTypes.MEDIA_ERROR) {
                    hls.recoverMediaError();
                    setMessage('Восстанавливаем воспроизведение…');
                } else {
                    setMessage('Не удалось воспроизвести эфир. Попробуйте открыть источник.');
                    resetPlayer({saveRecording: true});
                }
            });
            hls.attachMedia(video);
            markPlayerStarted('hls');
            return;
        }

        video.hidden = true;
        setPlaceholder('Браузер не поддерживает HLS', 'Откройте официальный источник или используйте современный браузер.');
        setStreamButton('Повторить');
    }

    function playIframeStream() {
        frame.src = activeChannel.dataset.streamUrl || player.dataset.streamSrc;
        frame.hidden = false;
        placeholder.hidden = true;
        markPlayerStarted('iframe');
        setMessage('');
    }

    playButton.addEventListener('click', async () => {
        if (activePlayerKind) {
            resetPlayer({saveRecording: true});
            return;
        }
        if (activeChannel.dataset.streamKind === 'mid') await playMidStream();
        else playIframeStream();
    });

    channelButtons.forEach((button) => {
        button.addEventListener('click', () => {
            if (button === activeChannel) return;
            resetPlayer({saveRecording: true});
            activeChannel = button;
            channelButtons.forEach((item) => item.classList.toggle('active', item === button));
            sourceLink.href = button.dataset.sourceUrl;
            sourceLink.textContent = 'Открыть источник ↗';
            setMessage('');
        });
    });

    function capturedPlayerStream() {
        if (activePlayerKind !== 'hls' || video.paused) return null;
        const capture = video.captureStream || video.mozCaptureStream;
        if (typeof capture !== 'function') return null;
        try {
            const stream = capture.call(video);
            if (stream.getAudioTracks().length) return stream;
            stream.getTracks().forEach((track) => track.stop());
        } catch (error) {
            return null;
        }
        return null;
    }

    async function captureAudioStream() {
        const directStream = capturedPlayerStream();
        if (directStream) {
            setMessage('Запись идёт прямо из плеера МИД — дополнительных окон нет.');
            return directStream;
        }
        if (!navigator.mediaDevices?.getDisplayMedia) return null;
        setMessage('Выберите «Текущая вкладка» и включите передачу звука.');
        return navigator.mediaDevices.getDisplayMedia({
            video: {frameRate: {ideal: 1, max: 5}},
            audio: true,
            preferCurrentTab: true,
            selfBrowserSurface: 'include',
            surfaceSwitching: 'exclude',
            monitorTypeSurfaces: 'exclude',
            systemAudio: 'include',
        });
    }

    async function startRecording() {
        setMessage('');
        if (!activePlayerKind) {
            setMessage('Сначала запустите эфир.');
            return;
        }
        if (!window.MediaRecorder) {
            setMessage('Этот браузер не поддерживает запись звука.');
            return;
        }
        try {
            captureStream = await captureAudioStream();
            if (!captureStream) {
                setMessage('Этот браузер не поддерживает запись звука вкладки.');
                return;
            }
            const audioTracks = captureStream.getAudioTracks();
            if (!audioTracks.length) {
                stopTracks();
                setMessage('Звук не передан. Повторите и включите «Передавать звук вкладки».');
                return;
            }
            const audioStream = new MediaStream(audioTracks);
            const preferredTypes = ['audio/webm;codecs=opus', 'audio/webm', 'video/webm;codecs=opus'];
            const mimeType = preferredTypes.find((type) => MediaRecorder.isTypeSupported(type)) || '';
            mediaRecorder = new MediaRecorder(audioStream, mimeType ? {mimeType} : undefined);
            recordedChunks = [];
            recordingSlug = slugForChannel();
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
            captureStream.getTracks().forEach((track) => {
                track.addEventListener('ended', () => stopRecording(true), {once: true});
            });
            mediaRecorder.start(1000);
            startedAt = Date.now();
            updateTimer();
            timer = setInterval(updateTimer, 1000);
            recordState.textContent = 'Идёт запись';
            recordButton.textContent = '■ Остановить и сохранить';
            recordButton.classList.add('recording');
            recordButton.setAttribute('aria-pressed', 'true');
            recordButton.disabled = false;
            if (activePlayerKind !== 'hls') setMessage('Идёт запись звука выбранной вкладки.');
        } catch (error) {
            stopTracks();
            resetRecorderUi();
            setMessage(error?.name === 'NotAllowedError'
                ? 'Запись отменена.'
                : 'Не удалось начать запись. Проверьте разрешение браузера.');
        }
    }

    recordButton.addEventListener('click', async () => {
        if (isConverting) return;
        if (mediaRecorder?.state === 'recording') {
            stopRecording(true);
            return;
        }
        await startRecording();
    });

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
        destroyHlsPlayer();
    });

    updateClocks();
    setInterval(updateClocks, 30000);
})();
