"use strict";

const directIo = require("@ronomon/direct-io");

// etcher-sdk also requests aligned buffers for partial block-device reads when
// O_DIRECT is disabled. Electron 39 cannot create the native external buffers
// used by @ronomon/direct-io, but normal Buffers are valid for buffered I/O.
directIo.getAlignedBuffer = (size) => Buffer.allocUnsafe(size);

