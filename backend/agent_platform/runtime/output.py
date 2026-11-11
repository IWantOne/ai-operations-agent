"""Bounded subprocess pipe capture; each received chunk is persisted immediately."""
import asyncio
import base64
import codecs

CHUNK_BYTES = 16 * 1024
PREVIEW_BYTES = 64 * 1024


class ProcessOutput:
    def __init__(self, process, emit):
        self.process, self.emit = process, emit
        self.preview = {"stdout": bytearray(), "stderr": bytearray()}
        self.counts = {"stdout": 0, "stderr": 0}
        self.sequence = 0
        self.failure = asyncio.get_running_loop().create_future()
        self.readers = [asyncio.create_task(self._read(name, getattr(process, name)))
                        for name in ("stdout", "stderr")]
        self.completion = asyncio.create_task(self._finish())

    async def _read(self, name, pipe):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while True:
                raw = await pipe.read(CHUNK_BYTES)
                text = decoder.decode(raw, final=not raw)
                if not raw and not text:
                    break
                offset = self.counts[name]
                self.counts[name] += len(raw)
                preview = self.preview[name]
                preview.extend(raw[:max(0, PREVIEW_BYTES - len(preview))])
                self.sequence += 1
                if not self.failure.done():
                    try:
                        self.emit({"stream": name, "sequence": self.sequence, "byte_offset": offset,
                                   "text": text, "raw_base64": base64.b64encode(raw).decode("ascii")})
                    except Exception as exc:
                        # Tell the owner to stop; keep draining so process.wait cannot deadlock.
                        self.failure.set_result(exc)
                if not raw:
                    break
                await asyncio.sleep(0)
        except Exception as exc:
            if not self.failure.done():
                self.failure.set_result(exc)

    async def _finish(self):
        await asyncio.gather(*self.readers)
        await self.process.wait()

    async def wait(self):
        await asyncio.wait((self.completion, self.failure), return_when=asyncio.FIRST_COMPLETED)
        if self.failure.done():
            raise self.failure.result()
        await self.completion

    async def finish(self):
        await self.completion

    def metadata(self):
        return {"returncode": self.process.returncode,
                **{name + "_bytes": count for name, count in self.counts.items()},
                **{name + "_truncated": count > PREVIEW_BYTES for name, count in self.counts.items()}}

    def result(self):
        return {**self.metadata(), **{name: bytes(raw).decode("utf-8", errors="replace")
                                     for name, raw in self.preview.items()}}
