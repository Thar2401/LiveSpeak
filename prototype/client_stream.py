"""LiveSpeak Audio Streaming Client - Capture and stream audio to server.

This module provides audio capture, streaming, and client-side processing
for the LiveSpeak real-time captioning system.
"""

import asyncio
import json
import logging
import time
import wave
from pathlib import Path
from typing import Optional, Callable, Dict, Any

try:
    import pyaudio
    import websockets
    import numpy as np
except ImportError as e:
    logging.error(f"Missing dependencies: {e}")
    logging.error("Install with: pip install pyaudio websockets numpy")
    raise

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AudioStreamer:
    """Real-time audio capture and streaming client."""
    
    def __init__(self, server_url: str = "ws://localhost:8765"):
        self.server_url = server_url
        
        # Audio configuration
        self.sample_rate = 16000
        self.channels = 1
        self.chunk_size = 1024  # frames per chunk
        self.format = pyaudio.paInt16
        
        # PyAudio instance
        self.audio = None
        self.stream = None
        
        # WebSocket connection
        self.websocket = None
        self.connected = False
        
        # Streaming state
        self.streaming = False
        self.recording = False
        
        # Callbacks
        self.on_transcription: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self.on_connected: Optional[Callable] = None
        
        # Statistics
        self.stats = {
            "chunks_sent": 0,
            "bytes_sent": 0,
            "transcriptions_received": 0,
            "avg_latency_ms": 0,
            "connection_time": None
        }
    
    async def initialize(self):
        """Initialize audio system and connection."""
        try:
            # Initialize PyAudio
            self.audio = pyaudio.PyAudio()
            
            # Check audio devices
            self._log_audio_devices()
            
            logger.info(f"Audio system initialized - {self.sample_rate}Hz, {self.channels} channel(s)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize audio system: {e}")
            return False
    
    def _log_audio_devices(self):
        """Log available audio input devices."""
        try:
            device_count = self.audio.get_device_count()
            logger.info(f"Available audio devices ({device_count}):")
            
            for i in range(device_count):
                info = self.audio.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    logger.info(f"  {i}: {info['name']} (inputs: {info['maxInputChannels']})")
        except Exception as e:
            logger.warning(f"Could not enumerate audio devices: {e}")
    
    async def connect(self) -> bool:
        """Connect to LiveSpeak server."""
        try:
            logger.info(f"Connecting to {self.server_url}...")
            
            self.websocket = await websockets.connect(self.server_url)
            self.connected = True
            self.stats["connection_time"] = time.time()
            
            logger.info("Connected to LiveSpeak server")
            
            # Start message handler
            asyncio.create_task(self._handle_messages())
            
            if self.on_connected:
                self.on_connected()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self.connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from server and cleanup."""
        self.streaming = False
        self.recording = False
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        
        self.connected = False
        logger.info("Disconnected from server")
    
    async def start_streaming(self) -> bool:
        """Start real-time audio streaming."""
        if not self.connected:
            logger.error("Not connected to server")
            return False
        
        if self.streaming:
            logger.warning("Already streaming")
            return True
        
        try:
            # Open audio stream
            self.stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                stream_callback=self._audio_callback
            )
            
            self.streaming = True
            self.recording = True
            
            logger.info("Started audio streaming")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start streaming: {e}")
            return False
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio callback for real-time audio capture."""
        if self.streaming and self.connected:
            # Schedule async processing
            asyncio.create_task(self._send_audio_chunk(in_data))
        
        return (None, pyaudio.paContinue)
    
    async def _send_audio_chunk(self, audio_data: bytes):
        """Send audio chunk to server."""
        try:
            if self.websocket and self.connected:
                message = {
                    "type": "audio_chunk",
                    "audio_data": audio_data.hex(),
                    "timestamp": time.time(),
                    "chunk_id": f"chunk_{self.stats['chunks_sent']}",
                    "sample_rate": self.sample_rate,
                    "channels": self.channels,
                    "format": "int16"
                }
                
                await self.websocket.send(json.dumps(message))
                
                self.stats["chunks_sent"] += 1
                self.stats["bytes_sent"] += len(audio_data)
                
        except Exception as e:
            logger.error(f"Error sending audio chunk: {e}")
            if self.on_error:
                self.on_error(f"Audio send error: {e}")
    
    async def _handle_messages(self):
        """Handle incoming messages from server."""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                await self._process_server_message(data)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info("Server connection closed")
            self.connected = False
        except Exception as e:
            logger.error(f"Error handling server messages: {e}")
            if self.on_error:
                self.on_error(f"Message handling error: {e}")
    
    async def _process_server_message(self, data: Dict[str, Any]):
        """Process message from server."""
        msg_type = data.get("type")
        
        if msg_type == "transcription":
            result = data.get("result", {})
            
            # Update statistics
            self.stats["transcriptions_received"] += 1
            if "latency_ms" in result:
                # Simple moving average
                current_avg = self.stats["avg_latency_ms"]
                new_latency = result["latency_ms"]
                self.stats["avg_latency_ms"] = (current_avg * 0.8) + (new_latency * 0.2)
            
            # Call user callback
            if self.on_transcription:
                self.on_transcription(result)
            
            # Log transcription
            text = result.get("text", "")
            source = result.get("source", "unknown")
            confidence = result.get("confidence", 0.0)
            is_final = result.get("is_final", False)
            
            if text:
                status = "FINAL" if is_final else "interim"
                logger.info(f"[{source.upper()}] {status}: {text} (conf: {confidence:.2f})")
        
        elif msg_type == "config":
            logger.info(f"Server config received: {data.get('server_config', {})}")
        
        elif msg_type == "error":
            error_msg = data.get("message", "Unknown server error")
            logger.error(f"Server error: {error_msg}")
            if self.on_error:
                self.on_error(error_msg)
        
        elif msg_type == "pong":
            # Handle ping/pong for connection keep-alive
            pass
    
    async def stop_streaming(self):
        """Stop audio streaming."""
        self.streaming = False
        self.recording = False
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        
        logger.info("Stopped audio streaming")
    
    async def send_audio_file(self, file_path: str) -> bool:
        """Send pre-recorded audio file to server."""
        if not self.connected:
            logger.error("Not connected to server")
            return False
        
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                logger.error(f"Audio file not found: {file_path}")
                return False
            
            logger.info(f"Sending audio file: {file_path}")
            
            # Read WAV file
            with wave.open(str(file_path), 'rb') as wav_file:
                frames = wav_file.getnframes()
                sample_rate = wav_file.getframerate()
                channels = wav_file.getnchannels()
                
                logger.info(f"File info: {frames} frames, {sample_rate}Hz, {channels} channel(s)")
                
                # Read and send in chunks
                chunk_frames = self.chunk_size
                total_chunks = (frames + chunk_frames - 1) // chunk_frames
                
                for i in range(total_chunks):
                    audio_data = wav_file.readframes(chunk_frames)
                    
                    if audio_data:
                        message = {
                            "type": "audio_chunk",
                            "audio_data": audio_data.hex(),
                            "timestamp": time.time(),
                            "chunk_id": f"file_chunk_{i}",
                            "sample_rate": sample_rate,
                            "channels": channels,
                            "format": "int16",
                            "file_chunk": True,
                            "chunk_info": f"{i+1}/{total_chunks}"
                        }
                        
                        await self.websocket.send(json.dumps(message))
                        self.stats["chunks_sent"] += 1
                        self.stats["bytes_sent"] += len(audio_data)
                        
                        # Small delay to avoid overwhelming server
                        await asyncio.sleep(0.1)
            
            logger.info(f"Audio file sent successfully: {total_chunks} chunks")
            return True
            
        except Exception as e:
            logger.error(f"Error sending audio file: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        uptime = time.time() - self.stats["connection_time"] if self.stats["connection_time"] else 0
        
        return {
            "connection": {
                "connected": self.connected,
                "server_url": self.server_url,
                "uptime_seconds": uptime
            },
            "audio": {
                "streaming": self.streaming,
                "sample_rate": self.sample_rate,
                "channels": self.channels,
                "chunk_size": self.chunk_size
            },
            "performance": self.stats
        }
    
    def cleanup(self):
        """Cleanup audio resources."""
        if self.audio:
            self.audio.terminate()
            self.audio = None

# Demo and testing functions
async def demo_streaming():
    """Demonstrate real-time audio streaming."""
    print("LiveSpeak Audio Streaming Demo")
    print("=" * 40)
    
    client = AudioStreamer()
    
    # Setup callbacks
    def on_transcription(result):
        text = result.get("text", "")
        source = result.get("source", "unknown")
        is_final = result.get("is_final", False)
        
        if text:
            status = "[FINAL]" if is_final else "[interim]"
            print(f"{status} {source.upper()}: {text}")
    
    def on_error(error):
        print(f"ERROR: {error}")
    
    def on_connected():
        print("✅ Connected to LiveSpeak server")
    
    client.on_transcription = on_transcription
    client.on_error = on_error
    client.on_connected = on_connected
    
    try:
        # Initialize and connect
        if not await client.initialize():
            print("❌ Failed to initialize audio system")
            return
        
        if not await client.connect():
            print("❌ Failed to connect to server")
            return
        
        print("\n🎤 Starting real-time transcription...")
        print("Press Ctrl+C to stop\n")
        
        # Start streaming
        if await client.start_streaming():
            # Keep streaming until interrupted
            try:
                while client.streaming:
                    await asyncio.sleep(1)
                    
                    # Print stats every 10 seconds
                    if client.stats["chunks_sent"] % 100 == 0 and client.stats["chunks_sent"] > 0:
                        stats = client.get_stats()
                        print(f"\n📊 Stats: {stats['performance']['chunks_sent']} chunks sent, "
                              f"avg latency: {stats['performance']['avg_latency_ms']:.1f}ms\n")
            
            except KeyboardInterrupt:
                print("\n🛑 Stopping...")
        
        else:
            print("❌ Failed to start streaming")
    
    finally:
        await client.disconnect()
        client.cleanup()
        print("✅ Demo completed")

async def demo_file_processing():
    """Demonstrate processing audio files."""
    print("LiveSpeak File Processing Demo")
    print("=" * 40)
    
    client = AudioStreamer()
    
    # Setup callbacks
    transcription_results = []
    
    def on_transcription(result):
        transcription_results.append(result)
        text = result.get("text", "")
        source = result.get("source", "unknown")
        
        if text:
            print(f"{source.upper()}: {text}")
    
    client.on_transcription = on_transcription
    
    try:
        if not await client.initialize():
            return
        
        if not await client.connect():
            return
        
        # Process demo file
        demo_file = Path(__file__).parent / "demo_audio" / "sample_short.wav"
        
        if demo_file.exists():
            print(f"\n🎵 Processing file: {demo_file}")
            success = await client.send_audio_file(str(demo_file))
            
            if success:
                # Wait for results
                await asyncio.sleep(2)
                
                print(f"\n📝 Final Results ({len(transcription_results)} responses):")
                for i, result in enumerate(transcription_results, 1):
                    text = result.get("text", "")
                    confidence = result.get("confidence", 0.0)
                    source = result.get("source", "unknown")
                    
                    if text:
                        print(f"{i}. [{source}] {text} (confidence: {confidence:.2f})")
            else:
                print("❌ Failed to process file")
        else:
            print(f"❌ Demo file not found: {demo_file}")
    
    finally:
        await client.disconnect()
        client.cleanup()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "file":
        # File processing demo
        asyncio.run(demo_file_processing())
    else:
        # Real-time streaming demo
        asyncio.run(demo_streaming())