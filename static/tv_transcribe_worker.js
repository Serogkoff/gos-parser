/* Local, desktop-only speech recognition for the TV recorder. */

// Use the public package entry point documented by Transformers.js. The
// internal dist filename is not part of the CDN contract and may not exist.
const TRANSFORMERS_URL = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1';
const MODEL_ID = 'onnx-community/whisper-base';

let pipelinePromise = null;

function reportProgress(progress) {
    if (!progress || typeof progress !== 'object') return;
    const value = Number(progress.progress);
    self.postMessage({
        type: 'model-progress',
        value: Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : null,
        file: typeof progress.file === 'string' ? progress.file : '',
        status: typeof progress.status === 'string' ? progress.status : '',
    });
}

async function createPipeline() {
    const {env, pipeline} = await import(TRANSFORMERS_URL);
    env.allowLocalModels = false;
    env.useBrowserCache = true;

    const commonOptions = {progress_callback: reportProgress};
    if (self.navigator && self.navigator.gpu) {
        self.postMessage({
            type: 'status',
            message: 'Загружаем модель и подключаем видеокарту…',
        });
        try {
            return await pipeline('automatic-speech-recognition', MODEL_ID, {
                ...commonOptions,
                device: 'webgpu',
            });
        } catch (error) {
            self.postMessage({
                type: 'status',
                message: 'WebGPU недоступен — пробуем обработку процессором…',
            });
        }
    } else {
        self.postMessage({
            type: 'status',
            message: 'Загружаем модель для процессора…',
        });
    }
    return pipeline('automatic-speech-recognition', MODEL_ID, commonOptions);
}

function getPipeline() {
    if (!pipelinePromise) pipelinePromise = createPipeline();
    return pipelinePromise;
}

self.addEventListener('message', async (event) => {
    if (event.data?.type !== 'transcribe' || !event.data.audio) return;
    try {
        const transcriber = await getPipeline();
        self.postMessage({type: 'status', message: 'Распознаём речь…'});
        const result = await transcriber(new Float32Array(event.data.audio), {
            language: 'russian',
            task: 'transcribe',
            chunk_length_s: 30,
            stride_length_s: 5,
            return_timestamps: true,
        });
        self.postMessage({
            type: 'complete',
            text: typeof result?.text === 'string' ? result.text.trim() : '',
            chunks: Array.isArray(result?.chunks) ? result.chunks : [],
        });
    } catch (error) {
        pipelinePromise = null;
        self.postMessage({
            type: 'error',
            message: error instanceof Error ? error.message : String(error),
        });
    }
});
