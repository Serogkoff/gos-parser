# Third-party notices

## lamejs 1.2.1

The browser-side MP3 export uses the unmodified `lame.min.js` distribution
from [lamejs](https://github.com/zhuker/lamejs), a JavaScript port of the LAME
MP3 encoder. It is distributed under the GNU Lesser General Public License
(LGPL-3.0). The vendored source remains a separate file at
`static/vendor/lame.min.js` so it can be replaced or relinked independently.

The upstream project and corresponding source code are available at the link
above. No modifications were made to the vendored encoder.

## onnx-asr-web 0.1.3 and ONNX Runtime Web 1.24.3

Desktop TV transcription loads the pinned browser distribution of
[`onnx-asr-web`](https://github.com/SanderGi/onnx-asr-web) and its
[`onnxruntime-web`](https://github.com/microsoft/onnxruntime) runtime from
jsDelivr only after the user presses the transcription button. Both projects
are distributed under the MIT License.

## GigaAM v3 E2E RNNT and Silero VAD

Russian speech recognition uses the quantized ONNX files from
[`istupakov/gigaam-v3-onnx`](https://huggingface.co/istupakov/gigaam-v3-onnx),
based on the MIT-licensed
[`salute-developers/GigaAM`](https://github.com/salute-developers/GigaAM)
model, together with the MIT-licensed
[`onnx-community/silero-vad`](https://huggingface.co/onnx-community/silero-vad)
voice activity detector. Model files are downloaded and cached by the user's
desktop browser; they are not bundled with or processed by the gos-parser
server.
