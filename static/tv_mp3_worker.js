(() => {
    'use strict';

    let encoderLoaded = false;

    self.addEventListener('message', (event) => {
        const {samples, sampleRate, bitRate, encoderUrl} = event.data;
        try {
            if (!encoderLoaded) {
                importScripts(encoderUrl);
                encoderLoaded = true;
            }
            if (!self.lamejs?.Mp3Encoder) {
                throw new Error('MP3 encoder was not loaded');
            }

            const pcm = new Int16Array(samples);
            const encoder = new lamejs.Mp3Encoder(1, sampleRate, bitRate || 128);
            const blockSize = 1152;
            const chunks = [];
            let totalBytes = 0;

            for (let offset = 0; offset < pcm.length; offset += blockSize) {
                const encoded = encoder.encodeBuffer(pcm.subarray(offset, offset + blockSize));
                if (encoded.length) {
                    const chunk = new Uint8Array(encoded);
                    chunks.push(chunk);
                    totalBytes += chunk.length;
                }
                if (offset % (blockSize * 200) === 0) {
                    self.postMessage({
                        type: 'progress',
                        value: Math.min(99, Math.round((offset / pcm.length) * 100)),
                    });
                }
            }

            const flushed = encoder.flush();
            if (flushed.length) {
                const chunk = new Uint8Array(flushed);
                chunks.push(chunk);
                totalBytes += chunk.length;
            }

            const output = new Uint8Array(totalBytes);
            let position = 0;
            chunks.forEach((chunk) => {
                output.set(chunk, position);
                position += chunk.length;
            });
            self.postMessage({type: 'complete', buffer: output.buffer}, [output.buffer]);
        } catch (error) {
            self.postMessage({type: 'error', message: error?.message || String(error)});
        }
    });
})();
