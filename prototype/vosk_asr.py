"""Edge ASR Implementation using Vosk for real-time speech recognition.

This module provides local speech recognition capabilities with <100ms latency
for the LiveSpeak hybrid processing system.
"""

import json
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator

try:
    import vosk
    import soundfile as sf
    import numpy as np
except ImportError as e:
    logging.error(f"Missing dependencies: {e}")
    logging.error("Install with: pip install vosk soundfile numpy")
    raise

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VoskASR:
    """Vosk-based edge ASR processor for real-time speech recognition."""
    
    def __init__(self, model_path: Optional[str] = None, sample_rate: int = 16000):
        """
        Initialize Vosk ASR processor.
        
        Args:
            model_path: Path to Vosk model directory
            sample_rate: Audio sample rate (default 16kHz)
        """
        self.sample_rate = sample_rate
        self.model_path = model_path or self._get_default_model_path()
        self.model = None
        self.recognizer = None
        self.is_initialized = False
        
    def _get_default_model_path(self) -> str:
        """Get default model path, download if needed."""
        # Check for available models in order of preference
        model_candidates = [
            "vosk-model-small-en-us-0.15",
            "vosk-model-en-us-0.22",
            "vosk-model-en-us-0.22-lgraph"
        ]
        
        for model_path in model_candidates:
            if Path(model_path).exists():
                return model_path
        
        # Return first candidate as default
        return model_candidates[0]
    
    async def initialize(self) -> bool:
        """Initialize Vosk model and recognizer."""
        try:
            if not Path(self.model_path).exists():
                logger.warning(f"Model not found at {self.model_path}")
                logger.info("Download models from: https://alphacephei.com/vosk/models")
                return False
                
            # Load model in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(
                None, vosk.Model, self.model_path
            )
            
            self.recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)  # Enable word-level timestamps
            
            self.is_initialized = True
            logger.info(f"Vosk ASR initialized with model: {self.model_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Vosk ASR: {e}")
            return False
    
    def process_audio_chunk(self, audio_data: bytes) -> Dict[str, Any]:
        """
        Process audio chunk and return transcription result.
        
        Args:
            audio_data: Raw audio bytes (16kHz, 16-bit, mono)
            
        Returns:
            Dict with transcription result, confidence, and timing
        """
        if not self.is_initialized:
            return {
                "text": "",
                "confidence": 0.0,
                "is_final": False,
                "processing_time_ms": 0,
                "error": "ASR not initialized"
            }
        
        start_time = time.time()
        
        try:
            # Convert audio data to numpy array
            audio_np = np.frombuffer(audio_data, dtype=np.int16)
            
            # Process with Vosk
            if self.recognizer.AcceptWaveform(audio_data):
                # Final result
                result = json.loads(self.recognizer.Result())
                is_final = True
            else:
                # Partial result
                result = json.loads(self.recognizer.PartialResult())
                is_final = False
            
            processing_time = (time.time() - start_time) * 1000  # ms
            
            return {
                "text": result.get("text", ""),
                "confidence": result.get("conf", 0.8),  # Vosk doesn't always provide confidence
                "is_final": is_final,
                "processing_time_ms": processing_time,
                "words": result.get("result", []),  # Word-level results with timestamps
                "error": None
            }
            
        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            logger.error(f"Error processing audio chunk: {e}")
            return {
                "text": "",
                "confidence": 0.0,
                "is_final": False,
                "processing_time_ms": processing_time,
                "error": str(e)
            }
    
    async def process_audio_stream(self, audio_stream: AsyncGenerator[bytes, None]) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Process continuous audio stream and yield transcription results.
        
        Args:
            audio_stream: Async generator of audio chunks
            
        Yields:
            Transcription results for each audio chunk
        """
        if not self.is_initialized:
            await self.initialize()
            
        async for audio_chunk in audio_stream:
            if audio_chunk:
                result = self.process_audio_chunk(audio_chunk)
                yield result
    
    def reset(self):
        """Reset recognizer state for new audio stream."""
        if self.recognizer:
            # Create new recognizer instance
            self.recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get ASR performance statistics."""
        return {
            "model_path": self.model_path,
            "sample_rate": self.sample_rate,
            "is_initialized": self.is_initialized,
            "supports_streaming": True,
            "supports_partial_results": True,
            "latency_target_ms": 100
        }

# Utility functions for audio file processing
async def transcribe_audio_file(file_path: str, model_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Transcribe an audio file using Vosk ASR.
    
    Args:
        file_path: Path to audio file
        model_path: Optional Vosk model path
        
    Returns:
        Complete transcription with metadata
    """
    try:
        # Load audio file
        audio_data, sample_rate = sf.read(file_path)
        
        # Convert to 16kHz mono if needed
        if sample_rate != 16000:
            import scipy.signal
            audio_data = scipy.signal.resample(audio_data, int(len(audio_data) * 16000 / sample_rate))
            sample_rate = 16000
        
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)  # Convert to mono
        
        # Convert to int16
        audio_data = (audio_data * 32767).astype(np.int16)
        
        # Initialize ASR
        asr = VoskASR(model_path, sample_rate)
        if not await asr.initialize():
            return {"error": "Failed to initialize ASR"}
        
        # Process entire audio
        start_time = time.time()
        result = asr.process_audio_chunk(audio_data.tobytes())
        
        # Get final result
        if asr.recognizer:
            final_result = json.loads(asr.recognizer.FinalResult())
            result.update(final_result)
        
        result["file_path"] = file_path
        result["duration_seconds"] = len(audio_data) / sample_rate
        result["total_processing_time_ms"] = (time.time() - start_time) * 1000
        
        return result
        
    except Exception as e:
        logger.error(f"Error transcribing file {file_path}: {e}")
        return {"error": str(e), "file_path": file_path}

if __name__ == "__main__":
    # Demo usage
    async def demo():
        """Demonstrate Vosk ASR functionality."""
        print("LiveSpeak Edge ASR Demo")
        print("=" * 30)
        
        # Test with demo audio file
        demo_file = Path(__file__).parent / "demo_audio" / "sample_short.wav"
        
        if demo_file.exists():
            print(f"Transcribing: {demo_file}")
            result = await transcribe_audio_file(str(demo_file))
            
            if "error" in result:
                print(f"Error: {result['error']}")
            else:
                print(f"Transcription: {result.get('text', 'No text detected')}")
                print(f"Confidence: {result.get('confidence', 0.0):.2f}")
                print(f"Processing time: {result.get('total_processing_time_ms', 0):.1f}ms")
        else:
            print(f"Demo file not found: {demo_file}")
            print("Please add an audio file to demo_audio/sample_short.wav")
    
    asyncio.run(demo())