import io, logging, time
from .config import settings

logger=logging.getLogger(__name__)

class SpeechService:
    def transcribe(self, audio: bytes, filename: str, language: str):
        start=time.perf_counter()
        logger.debug("Speech transcription started: format=%s bytes=%d language=%s provider=%s",filename.rsplit(".",1)[-1] if "." in filename else "unknown",len(audio),language,settings.stt_provider)
        if len(audio)>settings.max_audio_mb*1024*1024: raise ValueError(f"Audio exceeds {settings.max_audio_mb} MB limit")
        if not audio: raise ValueError("Audio file is empty")
        if settings.stt_provider=="faster-whisper":
            try: from faster_whisper import WhisperModel
            except ImportError as e: raise RuntimeError("Local STT unavailable. Install with pip install -e '.[models]' and set GSA_STT_PROVIDER=faster-whisper") from e
            model=WhisperModel(settings.stt_model,device="cpu",compute_type="int8")
            try: segments,_=model.transcribe(io.BytesIO(audio),language={"en":"en","bn":"bn","hi":"hi"}[language],vad_filter=True)
            except Exception as e: raise ValueError("Audio could not be decoded. Use WAV, MP3, M4A or another supported format.") from e
            transcript=" ".join(seg.text.strip() for seg in segments).strip()
            if not transcript: raise ValueError("No speech was detected")
            result={"transcription":transcript,"requested_language":language,"detected_language":None,"status":"success","model_id":settings.stt_model,"processing_time_ms":round((time.perf_counter()-start)*1000)}
            logger.debug("Speech transcription completed: model=%s characters=%d elapsed_ms=%d",settings.stt_model,len(transcript),result["processing_time_ms"])
            return result
        raise RuntimeError("Speech recognition is not configured. Set GSA_STT_PROVIDER=faster-whisper and install the optional local model dependencies; text questions remain available.")
