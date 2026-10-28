# Third-party notices

## lamejs 1.2.1

The browser-side MP3 export uses the unmodified `lame.min.js` distribution
from [lamejs](https://github.com/zhuker/lamejs), a JavaScript port of the LAME
MP3 encoder. It is distributed under the GNU Lesser General Public License
(LGPL-3.0). The vendored source remains a separate file at
`static/vendor/lame.min.js` so it can be replaced or relinked independently.

The upstream project and corresponding source code are available at the link
above. No modifications were made to the vendored encoder.

## Transformers.js 3.8.1

Desktop TV transcription loads the pinned browser distribution of
[`@huggingface/transformers`](https://github.com/huggingface/transformers.js)
from jsDelivr only after the user presses the transcription button. The
library is distributed under the Apache License 2.0.

## Whisper base

Speech recognition uses the multilingual
[`onnx-community/whisper-base`](https://huggingface.co/onnx-community/whisper-base)
model, an ONNX conversion of OpenAI Whisper for Transformers.js. Model files
are downloaded and cached by the user's desktop browser; they are not bundled
with or processed by the gos-parser server.
