/* Russian speech recognition in the user's desktop browser. */

const ASR_LIBRARY_URL = 'https://cdn.jsdelivr.net/npm/onnx-asr-web@0.1.3/browser/+esm';
const ORT_WASM_URL = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.24.3/dist/';
const MODEL_BASE_URL = 'https://huggingface.co/istupakov/gigaam-v3-onnx/resolve/main/';
const VAD_MODEL_ID = 'onnx-community/silero-vad';
const GIGAAM_CONFIG = {
    model_type: 'gigaam',
    version: 'v3_e2e',
    features_size: 64,
    subsampling_factor: 4,
    max_tokens_per_step: 3,
};

let modelPromise = null;

function postStatus(message, value = null) {
    self.postMessage({type: 'status', message});
    if (Number.isFinite(value)) {
        self.postMessage({type: 'model-progress', value, message});
    }
}

async function gigaamFetch(input, options = {}) {
    const originalUrl = typeof input === 'string' ? input : input.url;
    const url = new URL(originalUrl);
    if (url.pathname.endsWith('/config.json')) {
        return new Response(JSON.stringify(GIGAAM_CONFIG), {
            status: 200,
            headers: {'Content-Type': 'application/json'},
        });
    }
    if (url.pathname.endsWith('/v3_e2e_vocab.txt')) {
        url.pathname = url.pathname.replace(
            '/v3_e2e_vocab.txt',
            '/v3_e2e_rnnt_vocab.txt',
        );
    }
    return fetch(url.toString(), options);
}

async function createModel() {
    postStatus('Загружаем модуль GigaAM…', 5);
    const {
        configureOrtWeb,
        loadHuggingfaceVadModel,
        loadLocalModel,
    } = await import(ASR_LIBRARY_URL);

    configureOrtWeb({
        wasmPaths: ORT_WASM_URL,
        numThreads: self.crossOriginIsolated ? 2 : 1,
        simd: true,
    });

    postStatus('Загружаем модуль выделения речи…', 12);
    const vadModel = await loadHuggingfaceVadModel(VAD_MODEL_ID, {
        quantization: 'int8',
        sessionOptions: {executionProviders: ['wasm']},
    });

    postStatus('Загружаем GigaAM v3 (~226 МБ, только при первом запуске)…', 20);
    const model = await loadLocalModel(MODEL_BASE_URL, {
        fetch: gigaamFetch,
        quantization: 'int8',
        vadModel,
        vadOptions: {
            minSpeechMs: 250,
            minSilenceMs: 450,
            speechPadMs: 180,
        },
        sessionOptions: {
            executionProviders: ['wasm'],
            graphOptimizationLevel: 'all',
        },
        decoderOptions: {maxSymbols: 3},
    });
    postStatus('GigaAM готова.', 100);
    return model;
}

function getModel() {
    if (!modelPromise) modelPromise = createModel();
    return modelPromise;
}

function groupWords(words) {
    if (!Array.isArray(words) || !words.length) return [];
    const chunks = [];
    let current = [];
    let start = null;
    let end = null;

    words.forEach((item) => {
        const word = String(item?.word || '').trim();
        if (!word) return;
        const wordStart = Number(item.start);
        const wordEnd = Number(item.end);
        if (start === null && Number.isFinite(wordStart)) start = wordStart;
        if (Number.isFinite(wordEnd)) end = wordEnd;
        current.push(word);
        const sentenceEnd = /[.!?…]$/.test(word);
        const longChunk = Number.isFinite(start) && Number.isFinite(end) && end - start >= 18;
        if (sentenceEnd || longChunk) {
            chunks.push({text: current.join(' '), timestamp: [start, end]});
            current = [];
            start = null;
            end = null;
        }
    });
    if (current.length) chunks.push({text: current.join(' '), timestamp: [start, end]});
    return chunks;
}

function friendlyError(error) {
    const detail = error instanceof Error ? error.message : String(error);
    if (/fetch|network|load|http|failed/i.test(detail)) {
        return 'Не удалось скачать GigaAM. Проверьте доступ к Hugging Face и повторите.';
    }
    if (/memory|allocation|out of bounds/i.test(detail)) {
        return 'Компьютеру не хватило памяти для GigaAM. Закройте лишние вкладки и повторите.';
    }
    return `Ошибка GigaAM: ${detail}`;
}

self.addEventListener('message', async (event) => {
    if (event.data?.type !== 'transcribe' || !event.data.audio) return;
    try {
        const model = await getModel();
        postStatus('GigaAM распознаёт речь…');
        const result = await model.transcribeSamples(
            new Float32Array(event.data.audio),
            16000,
        );
        self.postMessage({
            type: 'complete',
            text: typeof result?.text === 'string' ? result.text.trim() : '',
            chunks: groupWords(result?.words),
        });
    } catch (error) {
        modelPromise = null;
        self.postMessage({type: 'error', message: friendlyError(error)});
    }
});
