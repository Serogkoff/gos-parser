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
    const transcriptPanel = document.getElementById('tv-transcript');
    const transcribeButton = document.getElementById('tv-transcribe');
    const transcriptStatus = document.getElementById('tv-transcript-status');
    const transcriptProgress = document.getElementById('tv-transcript-progress');
    const transcriptProgressValue = document.getElementById('tv-transcript-progress-value');
    const transcriptText = document.getElementById('tv-transcript-text');
    const transcriptActions = document.getElementById('tv-transcript-actions');
    const transcriptCopy = document.getElementById('tv-transcript-copy');
    const transcriptDownload = document.getElementById('tv-transcript-download');
    const transcriptMode = document.getElementById('tv-transcript-mode');
    const transcriberSetup = document.getElementById('tv-transcriber-setup');
    const transcriberState = document.getElementById('tv-transcriber-state');
    const transcriberDownload = document.getElementById('tv-transcriber-download');
    const desktopTranscriptionEnabled = window.matchMedia('(min-width: 921px)').matches;

    let activeChannel = channelButtons.find((button) => button.classList.contains('active')) || channelButtons[0];
    let activePlayerKind = '';
    let hls = null;
    let midFallbackTimer = null;
    let pendingMidRelayUrl = '';
    let captureStream = null;
    let mediaRecorder = null;
    let recordedChunks = [];
    let timer = null;
    let startedAt = 0;
    let saveWhenStopped = false;
    let conversionWorker = null;
    let isConverting = false;
    let recordingSlug = 'tv';
    let lastRecordingBlob = null;
    let lastRecordingSlug = 'tv';
    let localTranscriptionJob = '';
    let isTranscribing = false;
    let completedTranscript = '';

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

    function downloadNamedBlob(blob, filename) {
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    }

    function resetTranscription({hide = false, discardRecording = false} = {}) {
        cancelLocalTranscription();
        isTranscribing = false;
        completedTranscript = '';
        if (discardRecording) lastRecordingBlob = null;
        if (!transcriptPanel) return;
        transcriptPanel.hidden = hide || !desktopTranscriptionEnabled || !lastRecordingBlob;
        transcribeButton.disabled = false;
        transcribeButton.textContent = 'Расшифровать';
        transcriptStatus.textContent = 'Локальный GigaAM обработает запись на этом компьютере.';
        transcriptProgress.hidden = true;
        transcriptProgressValue.style.width = '0%';
        transcriptText.hidden = true;
        transcriptText.value = '';
        transcriptActions.hidden = true;
    }

    function prepareTranscription(sourceBlob) {
        if (!desktopTranscriptionEnabled || !transcriptPanel) return;
        lastRecordingBlob = sourceBlob;
        lastRecordingSlug = recordingSlug;
        resetTranscription();
        transcriptPanel.scrollIntoView({block: 'nearest', behavior: 'smooth'});
    }

    async function decodeAudioForTranscription(blob) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        const OfflineAudioContextClass = window.OfflineAudioContext || window.webkitOfflineAudioContext;
        if (!AudioContextClass || !OfflineAudioContextClass) {
            throw new Error('Браузер не поддерживает локальную обработку аудио.');
        }

        transcriptStatus.textContent = 'Подготавливаем аудио…';
        const audioContext = new AudioContextClass();
        let decoded;
        try {
            decoded = await audioContext.decodeAudioData(await blob.arrayBuffer());
        } finally {
            await audioContext.close();
        }
        if (decoded.duration > 4 * 60 * 60) {
            throw new Error('Одна запись должна быть не длиннее четырёх часов.');
        }

        const sampleRate = 16000;
        const frameCount = Math.max(1, Math.ceil(decoded.duration * sampleRate));
        const offlineContext = new OfflineAudioContextClass(1, frameCount, sampleRate);
        const source = offlineContext.createBufferSource();
        source.buffer = decoded;
        source.connect(offlineContext.destination);
        source.start(0);
        const rendered = await offlineContext.startRendering();
        return new Float32Array(rendered.getChannelData(0));
    }

    function finishTranscription() {
        isTranscribing = false;
        transcribeButton.disabled = false;
        transcribeButton.textContent = 'Расшифровать снова';
    }

    function pcmToWav(samples, sampleRate = 16000) {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);
        const write = (offset, value) => {
            for (let index = 0; index < value.length; index += 1) {
                view.setUint8(offset + index, value.charCodeAt(index));
            }
        };
        write(0, 'RIFF');
        view.setUint32(4, 36 + samples.length * 2, true);
        write(8, 'WAVE');
        write(12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        write(36, 'data');
        view.setUint32(40, samples.length * 2, true);
        for (let index = 0; index < samples.length; index += 1) {
            const sample = Math.max(-1, Math.min(1, samples[index]));
            view.setInt16(44 + index * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
        }
        return new Blob([buffer], {type: 'audio/wav'});
    }

    async function localRequest(path, options = {}) {
        const response = await fetch(`${player.dataset.localTranscriberUrl}${path}`, {
            mode: 'cors',
            credentials: 'omit',
            cache: 'no-store',
            ...options,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || `Локальный сервис ответил ${response.status}`);
        return payload;
    }

    async function cancelLocalTranscription() {
        const jobId = localTranscriptionJob;
        localTranscriptionJob = '';
        if (!jobId) return;
        try {
            await localRequest(`/jobs/${jobId}`, {method: 'DELETE'});
        } catch (_) {
            // The helper may already be closed; its temporary files are cleaned later.
        }
    }

    async function uploadToLocalTranscriber(wavBlob) {
        await localRequest('/health');
        const job = await localRequest('/jobs', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                filename: `${lastRecordingSlug}.wav`,
                size: wavBlob.size,
                mode: transcriptMode?.value || 'fast',
            }),
        });
        localTranscriptionJob = job.job_id;
        const chunkSize = 5 * 1024 * 1024;
        for (let offset = 0; offset < wavBlob.size; offset += chunkSize) {
            const chunk = wavBlob.slice(offset, Math.min(offset + chunkSize, wavBlob.size));
            await localRequest(`/jobs/${job.job_id}/upload`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/octet-stream',
                    'X-Upload-Offset': String(offset),
                },
                body: chunk,
            });
            const uploaded = Math.round(Math.min(offset + chunk.size, wavBlob.size) / wavBlob.size * 100);
            transcriptProgressValue.style.width = `${uploaded}%`;
            transcriptStatus.textContent = `Передаём запись локально: ${uploaded}%`;
        }
        await localRequest(`/jobs/${job.job_id}/start`, {method: 'POST'});
        return job.job_id;
    }

    function wait(milliseconds) {
        return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
    }

    async function checkLocalTranscriber() {
        if (!desktopTranscriptionEnabled || !transcriberSetup) return;
        try {
            const health = await localRequest('/health');
            transcriberSetup.classList.add('is-ready');
            transcriberState.textContent = `${health.engine || 'GigaAM'} готов к работе.`;
            transcriberDownload.textContent = 'Переустановить';
        } catch (_) {
            transcriberSetup.classList.remove('is-ready');
            transcriberState.textContent = 'Не установлен — скачайте и запустите установщик.';
            transcriberDownload.textContent = 'Скачать для Windows';
        }
    }

    async function waitForLocalTranscript(jobId) {
        while (localTranscriptionJob === jobId) {
            const job = await localRequest(`/jobs/${jobId}`);
            if (job.status === 'complete') return job;
            if (job.status === 'error') throw new Error(job.error || 'Локальное распознавание завершилось с ошибкой.');
            const progress = Math.max(1, Number(job.progress) || 1);
            transcriptProgressValue.style.width = `${progress}%`;
            transcriptStatus.textContent = job.status === 'queued'
                ? 'Запись в локальной очереди…'
                : `Распознаём фрагмент ${job.fragment || 1}: ${progress}%`;
            await wait(750);
        }
        throw new Error('Расшифровка отменена.');
    }

    async function startTranscription() {
        if (!desktopTranscriptionEnabled || !lastRecordingBlob || isTranscribing) return;
        isTranscribing = true;
        completedTranscript = '';
        transcribeButton.disabled = true;
        transcribeButton.textContent = 'Обрабатываем…';
        transcriptText.hidden = true;
        transcriptActions.hidden = true;
        transcriptProgress.hidden = false;
        transcriptProgressValue.style.width = '2%';

        try {
            transcriptStatus.textContent = 'Подготавливаем WAV для локального GigaAM…';
            const audio = await decodeAudioForTranscription(lastRecordingBlob);
            const wavBlob = pcmToWav(audio);
            const jobId = await uploadToLocalTranscriber(wavBlob);
            const result = await waitForLocalTranscript(jobId);
            completedTranscript = String(result.text || '').trim();
            transcriptText.value = completedTranscript || 'Речь не распознана.';
            transcriptText.hidden = false;
            transcriptActions.hidden = !completedTranscript;
            transcriptProgress.hidden = true;
            transcriptStatus.textContent = completedTranscript
                ? `Расшифровка готова: ${result.segments?.length || 0} фрагментов.`
                : 'В записи не удалось распознать речь.';
            await cancelLocalTranscription();
            finishTranscription();
        } catch (error) {
            const detail = String(error?.message || '');
            transcriptStatus.textContent = detail.includes('Failed to fetch')
                ? 'Локальный распознаватель не запущен. Установите его из пакета 17.77.'
                : detail || 'Не удалось подготовить запись.';
            transcriptProgress.hidden = true;
            await cancelLocalTranscription();
            finishTranscription();
        }
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
            prepareTranscription(sourceBlob);
            setMessage('MP3 сохранён на устройство.');
            return;
        }

        try {
            const mp3Blob = await convertToMp3(sourceBlob);
            downloadBlob(mp3Blob, 'mp3');
            prepareTranscription(mp3Blob);
            setMessage('MP3 сохранён на устройство.');
        } catch (error) {
            downloadBlob(sourceBlob, 'webm');
            prepareTranscription(sourceBlob);
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

    function clearMidFallback() {
        if (midFallbackTimer) clearTimeout(midFallbackTimer);
        midFallbackTimer = null;
        pendingMidRelayUrl = '';
    }

    function resetPlayer({saveRecording = true} = {}) {
        if (mediaRecorder?.state === 'recording') stopRecording(saveRecording);
        frame.src = 'about:blank';
        frame.hidden = true;
        destroyHlsPlayer();
        clearMidFallback();
        activePlayerKind = '';
        setPlaceholder('', '');
        setStreamButton('Запустить эфир');
    }

    function markPlayerStarted(kind) {
        activePlayerKind = kind;
        placeholder.hidden = true;
        setStreamButton('Остановить эфир', {running: true});
    }

    async function playHlsStream(streamUrl, {fallbackMessage = '', fallbackUrl = ''} = {}) {
        frame.src = 'about:blank';
        frame.hidden = true;
        video.hidden = false;
        placeholder.hidden = true;

        if (fallbackMessage) setMessage(fallbackMessage);
        if (video.canPlayType('application/vnd.apple.mpegurl')) {
            video.src = streamUrl;
            markPlayerStarted('hls');
            if (fallbackUrl) {
                video.addEventListener('error', async () => {
                    await playHlsStream(fallbackUrl, {
                        fallbackMessage: 'Прямой поток недоступен — эфир переключён через РИА.',
                    });
                }, {once: true});
            }
            try {
                await video.play();
            } catch (error) {
                setMessage('Поток готов. Нажмите Play внутри плеера.');
            }
            return true;
        }

        if (window.Hls?.isSupported()) {
            hls = new window.Hls({
                enableWorker: true,
                lowLatencyMode: false,
                startFragPrefetch: true,
                backBufferLength: 60,
                maxBufferLength: 90,
                maxMaxBufferLength: 180,
                manifestLoadingMaxRetry: 2,
                levelLoadingMaxRetry: 2,
                fragLoadingMaxRetry: 3,
                fragLoadingRetryDelay: 750,
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
                    if (fallbackUrl && streamUrl !== fallbackUrl) {
                        hls.destroy();
                        hls = null;
                        playHlsStream(fallbackUrl, {
                            fallbackMessage: 'Прямой поток недоступен — эфир переключён через РИА.',
                        });
                        return;
                    }
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
            return true;
        }

        video.hidden = true;
        setPlaceholder('Браузер не поддерживает HLS', 'Откройте официальный источник или используйте современный браузер.');
        setStreamButton('Повторить');
        return false;
    }

    function startMidDirect(embedUrl, relayUrl) {
        pendingMidRelayUrl = relayUrl;
        frame.src = embedUrl;
        frame.hidden = false;
        video.hidden = true;
        placeholder.hidden = true;
        markPlayerStarted('rutube');
        setMessage('Открываем официальный плеер RUTUBE…');
        midFallbackTimer = setTimeout(async () => {
            const fallbackUrl = pendingMidRelayUrl;
            clearMidFallback();
            if (activeChannel?.dataset.tvChannel !== 'mid' || activePlayerKind !== 'rutube') return;
            if (!fallbackUrl) {
                setMessage('RUTUBE не ответил. Попробуйте открыть источник.');
                return;
            }
            await playHlsStream(fallbackUrl, {
                fallbackMessage: 'RUTUBE не ответил — эфир переключён через РИА.',
            });
        }, 18000);
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

        if (!response?.ok || !payload.available || (!payload.embed_url && !payload.stream_url)) {
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
        if (payload.embed_url) {
            startMidDirect(payload.embed_url, payload.stream_url || '');
            return;
        }
        await playHlsStream(payload.stream_url);
    }

    async function playRussia24Stream() {
        setStreamButton('Подключаемся…', {disabled: true});
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
            payload = {available: false};
        }
        if (!response?.ok || !payload.available || !payload.stream_url) {
            setPlaceholder('Эфир временно недоступен', 'Попробуйте повторить подключение.');
            setStreamButton('Повторить');
            return;
        }
        sourceLink.href = payload.external_url || activeChannel.dataset.sourceUrl;
        await playHlsStream(payload.direct_stream_url || payload.stream_url, {
            fallbackUrl: payload.direct_stream_url ? payload.stream_url : '',
        });
    }

    window.addEventListener('message', (event) => {
        if (event.origin !== 'https://rutube.ru' || event.source !== frame.contentWindow) return;
        let payload = event.data;
        if (typeof payload === 'string') {
            try {
                payload = JSON.parse(payload);
            } catch (error) {
                return;
            }
        }
        if (!payload || typeof payload !== 'object') return;
        if (payload.type === 'player:ready') {
            frame.contentWindow?.postMessage(JSON.stringify({type: 'player:play', data: {}}), 'https://rutube.ru');
        }
        const state = payload?.data?.state;
        if (state === 'playing' || payload.type === 'player:adStart') {
            clearMidFallback();
            setMessage('');
        }
    });

    playButton.addEventListener('click', async () => {
        if (activePlayerKind) {
            resetPlayer({saveRecording: true});
            return;
        }
        if (activeChannel.dataset.streamKind === 'mid') await playMidStream();
        else await playRussia24Stream();
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
        resetTranscription({hide: true, discardRecording: true});
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

    transcribeButton?.addEventListener('click', startTranscription);
    transcriptCopy?.addEventListener('click', async () => {
        if (!completedTranscript) return;
        try {
            await navigator.clipboard.writeText(completedTranscript);
            transcriptStatus.textContent = 'Текст скопирован.';
        } catch (error) {
            transcriptText.hidden = false;
            transcriptText.focus();
            transcriptText.select();
            transcriptStatus.textContent = 'Текст выделен — нажмите Ctrl+C.';
        }
    });
    transcriptDownload?.addEventListener('click', () => {
        if (!completedTranscript) return;
        const stamp = new Date().toISOString().replace(/[:.]/g, '-');
        downloadNamedBlob(
            new Blob([completedTranscript], {type: 'text/plain;charset=utf-8'}),
            `${lastRecordingSlug}-${stamp}.txt`,
        );
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
        cancelLocalTranscription();
        stopRecording(false);
        destroyHlsPlayer();
    });

    updateClocks();
    checkLocalTranscriber();
    setInterval(updateClocks, 30000);
})();
