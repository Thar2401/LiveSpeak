#!/usr/bin/env python3
"""LiveSpeak Launcher - Start the real-time captioning system.

This script provides an easy way to start the LiveSpeak server and client
components for testing and development.
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

# Add prototype directory to path
sys.path.insert(0, str(Path(__file__).parent / "prototype"))

from server import start_server
from client_stream import demo_streaming, demo_file_processing
from vosk_asr import transcribe_audio_file
from cloud_stub import CloudASRManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def print_banner():
    """Print LiveSpeak banner."""
    banner = """
┌─────────────────────────────────────────────────────────┐
│      🎤 LiveSpeak - Real-Time Speech-to-Text System      │
│                                                       │
│  Hybrid Edge-Cloud Processing • <100ms Latency      │
│  Multi-language Support • WebSocket Streaming       │
└─────────────────────────────────────────────────────────┘
    """
    print(banner)

async def check_dependencies():
    """Check if required dependencies are available."""
    print("🔍 Checking dependencies...")
    
    missing = []
    
    try:
        import vosk
        print("✅ Vosk ASR - Available")
    except ImportError:
        print("❌ Vosk ASR - Missing")
        missing.append("vosk")
    
    try:
        import websockets
        print("✅ WebSockets - Available")
    except ImportError:
        print("❌ WebSockets - Missing")
        missing.append("websockets")
    
    try:
        import pyaudio
        print("✅ PyAudio - Available")
    except ImportError:
        print("❌ PyAudio - Missing (needed for live audio)")
        missing.append("pyaudio")
    
    try:
        import tornado
        print("✅ Tornado - Available")
    except ImportError:
        print("❌ Tornado - Missing")
        missing.append("tornado")
    
    # Check cloud services
    cloud_manager = CloudASRManager()
    cloud_status = cloud_manager.get_configuration_status()
    
    google_ok = cloud_status["google"]["sdk_available"] and cloud_status["google"]["configured"]
    azure_ok = cloud_status["azure"]["sdk_available"] and cloud_status["azure"]["configured"]
    
    print(f"✅ Google Cloud Speech - {'Configured' if google_ok else 'Not configured'}")
    print(f"✅ Azure Speech - {'Configured' if azure_ok else 'Not configured'}")
    
    if missing:
        print(f"\n❌ Missing dependencies: {', '.join(missing)}")
        print("\nInstall with:")
        print(f"pip install {' '.join(missing)}")
        return False
    
    print("\n✅ All core dependencies available!")
    return True

async def run_server():
    """Start the LiveSpeak server."""
    print("🚀 Starting LiveSpeak server...")
    print("\nServer endpoints:")
    print("  Web Interface: http://localhost:8080")
    print("  WebSocket API: ws://localhost:8765")
    print("  Server Status: http://localhost:8080/status")
    print("\nPress Ctrl+C to stop\n")
    
    try:
        await start_server()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server error: {e}")
        raise

async def run_client_demo():
    """Run client streaming demo."""
    print("🎤 Starting client streaming demo...")
    print("Make sure the server is running first!\n")
    
    await demo_streaming()

async def run_file_demo(audio_file: str):
    """Run file processing demo."""
    print(f"🎵 Processing audio file: {audio_file}")
    
    if not Path(audio_file).exists():
        print(f"❌ File not found: {audio_file}")
        return
    
    # Option 1: Direct file transcription (edge only)
    print("\n1. Direct file transcription (Edge ASR):")
    result = await transcribe_audio_file(audio_file)
    
    if "error" in result:
        print(f"❌ Error: {result['error']}")
    else:
        print(f"📝 Transcription: {result.get('text', 'No text detected')}")
        print(f"📊 Confidence: {result.get('confidence', 0.0):.2f}")
        print(f"⏱️  Processing time: {result.get('total_processing_time_ms', 0):.1f}ms")
    
    # Option 2: Stream to server
    print("\n2. Streaming to server (Hybrid processing):")
    await demo_file_processing()

async def check_setup():
    """Check system setup and provide guidance."""
    print("🔧 LiveSpeak Setup Check")
    print("=" * 30)
    
    # Check Vosk models
    print("\n🤖 Vosk Models:")
    model_paths = [
        "vosk-model-en-us-0.22",
        "vosk-model-en-us-0.22-lgraph",
        "vosk-model-small-en-us-0.15"
    ]
    
    models_found = False
    for model_path in model_paths:
        if Path(model_path).exists():
            print(f"✅ Found: {model_path}")
            models_found = True
        else:
            print(f"❌ Missing: {model_path}")
    
    if not models_found:
        print("\n📝 Download Vosk models from: https://alphacephei.com/vosk/models")
        print("Recommended: vosk-model-en-us-0.22 (best accuracy)")
        print("Alternative: vosk-model-small-en-us-0.15 (smaller size)")
    
    # Check audio files
    print("\n🎵 Demo Audio:")
    demo_audio_dir = Path("prototype/demo_audio")
    if demo_audio_dir.exists():
        audio_files = list(demo_audio_dir.glob("*.wav"))
        if audio_files:
            for audio_file in audio_files:
                print(f"✅ Found: {audio_file}")
        else:
            print("❌ No .wav files found in demo_audio/")
    else:
        print("❌ demo_audio/ directory not found")
    
    # Check cloud configuration
    print("\n☁️ Cloud Services:")
    cloud_manager = CloudASRManager()
    await cloud_manager.initialize()
    available = cloud_manager.get_available_services()
    
    if available:
        print(f"✅ Available cloud services: {', '.join(available)}")
    else:
        print("❌ No cloud services configured")
        print("\nTo enable cloud processing:")
        print("  Google: Set GOOGLE_APPLICATION_CREDENTIALS and GOOGLE_CLOUD_PROJECT")
        print("  Azure: Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION")

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="LiveSpeak Real-Time Captioning System")
    parser.add_argument("command", choices=[
        "server", "client", "file", "check", "setup"
    ], help="Command to run")
    parser.add_argument("--file", "-f", help="Audio file path for file processing")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    print_banner()
    
    async def run_command():
        # Check dependencies first (except for setup command)
        if args.command != "setup":
            if not await check_dependencies():
                print("\n❌ Cannot continue with missing dependencies")
                sys.exit(1)
        
        if args.command == "server":
            await run_server()
        
        elif args.command == "client":
            await run_client_demo()
        
        elif args.command == "file":
            if args.file:
                await run_file_demo(args.file)
            else:
                # Use demo file
                demo_file = Path("prototype/demo_audio/sample_short.wav")
                if demo_file.exists():
                    await run_file_demo(str(demo_file))
                else:
                    print("❌ No demo file found. Use --file to specify audio file")
        
        elif args.command == "check":
            await check_dependencies()
        
        elif args.command == "setup":
            await check_setup()
    
    try:
        asyncio.run(run_command())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()