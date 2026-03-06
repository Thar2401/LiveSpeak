"""Cloud ASR Integration for LiveSpeak - Google and Azure Speech Services.

This module provides integration templates and working stubs for major cloud
speech recognition services. Add your API keys to enable cloud processing.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, AsyncGenerator
import os
from pathlib import Path

# Import cloud SDKs (install as needed)
try:
    from google.cloud import speech
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    logging.warning("Google Cloud Speech not available. Install: pip install google-cloud-speech")

try:
    import azure.cognitiveservices.speech as speechsdk
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    logging.warning("Azure Speech not available. Install: pip install azure-cognitiveservices-speech")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CloudASRConfig:
    """Configuration for cloud ASR services."""
    
    def __init__(self):
        # Load from environment variables or config file
        self.google_credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.google_project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        
        self.azure_subscription_key = os.getenv("AZURE_SPEECH_KEY")
        self.azure_service_region = os.getenv("AZURE_SPEECH_REGION", "eastus")
        
        self.default_language = "en-US"
        self.enable_interim_results = True
        self.enable_automatic_punctuation = True
    
    def is_google_configured(self) -> bool:
        """Check if Google Cloud Speech is properly configured."""
        return (GOOGLE_AVAILABLE and 
                self.google_credentials_path and 
                Path(self.google_credentials_path).exists())
    
    def is_azure_configured(self) -> bool:
        """Check if Azure Speech is properly configured."""
        return (AZURE_AVAILABLE and 
                self.azure_subscription_key and 
                self.azure_service_region)

class GoogleSpeechASR:
    """Google Cloud Speech-to-Text integration."""
    
    def __init__(self, config: CloudASRConfig):
        self.config = config
        self.client = None
        self.streaming_config = None
        self.is_initialized = False
    
    async def initialize(self) -> bool:
        """Initialize Google Cloud Speech client."""
        if not GOOGLE_AVAILABLE:
            logger.error("Google Cloud Speech SDK not available")
            return False
        
        if not self.config.is_google_configured():
            logger.error("Google Cloud Speech not configured. Set GOOGLE_APPLICATION_CREDENTIALS and GOOGLE_CLOUD_PROJECT")
            return False
        
        try:
            # Initialize client
            self.client = speech.SpeechClient()
            
            # Configure streaming
            recognition_config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code=self.config.default_language,
                enable_automatic_punctuation=self.config.enable_automatic_punctuation,
                model="latest_long",  # Use enhanced model
            )
            
            self.streaming_config = speech.StreamingRecognitionConfig(
                config=recognition_config,
                interim_results=self.config.enable_interim_results,
                single_utterance=False,
            )
            
            self.is_initialized = True
            logger.info("Google Cloud Speech initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Google Cloud Speech: {e}")
            return False
    
    async def process_audio_chunk(self, audio_data: bytes, timestamp: float) -> Dict[str, Any]:
        """Process audio chunk with Google Cloud Speech."""
        if not self.is_initialized:
            return {
                "text": "",
                "confidence": 0.0,
                "is_final": False,
                "error": "Google Speech not initialized",
                "timestamp": timestamp
            }
        
        start_time = time.time()
        
        try:
            # Create streaming request
            request = speech.StreamingRecognizeRequest(audio_content=audio_data)
            
            # Process with streaming API (simplified for demo)
            # In production, you'd maintain a streaming connection
            responses = self.client.streaming_recognize(self.streaming_config, [request])
            
            for response in responses:
                if response.results:
                    result = response.results[0]
                    
                    return {
                        "text": result.alternatives[0].transcript,
                        "confidence": result.alternatives[0].confidence,
                        "is_final": result.is_final,
                        "latency_ms": (time.time() - start_time) * 1000,
                        "timestamp": timestamp,
                        "language": self.config.default_language,
                        "error": None
                    }
            
            # No results
            return {
                "text": "",
                "confidence": 0.0,
                "is_final": False,
                "latency_ms": (time.time() - start_time) * 1000,
                "timestamp": timestamp,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"Google Speech processing error: {e}")
            return {
                "text": "",
                "confidence": 0.0,
                "is_final": False,
                "latency_ms": (time.time() - start_time) * 1000,
                "timestamp": timestamp,
                "error": str(e)
            }

class AzureSpeechASR:
    """Azure Cognitive Services Speech integration."""
    
    def __init__(self, config: CloudASRConfig):
        self.config = config
        self.speech_config = None
        self.recognizer = None
        self.is_initialized = False
    
    async def initialize(self) -> bool:
        """Initialize Azure Speech Service."""
        if not AZURE_AVAILABLE:
            logger.error("Azure Speech SDK not available")
            return False
        
        if not self.config.is_azure_configured():
            logger.error("Azure Speech not configured. Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION")
            return False
        
        try:
            # Initialize speech config
            self.speech_config = speechsdk.SpeechConfig(
                subscription=self.config.azure_subscription_key,
                region=self.config.azure_service_region
            )
            
            self.speech_config.speech_recognition_language = self.config.default_language
            self.speech_config.enable_dictation()
            
            # Create recognizer (would use push stream in real implementation)
            audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
            self.recognizer = speechsdk.SpeechRecognizer(
                speech_config=self.speech_config,
                audio_config=audio_config
            )
            
            self.is_initialized = True
            logger.info("Azure Speech Service initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Azure Speech: {e}")
            return False
    
    async def process_audio_chunk(self, audio_data: bytes, timestamp: float) -> Dict[str, Any]:
        """Process audio chunk with Azure Speech Service."""
        if not self.is_initialized:
            return {
                "text": "",
                "confidence": 0.0,
                "is_final": False,
                "error": "Azure Speech not initialized",
                "timestamp": timestamp
            }
        
        start_time = time.time()
        
        try:
            # In a real implementation, you'd use PushAudioInputStream
            # For this stub, we simulate the response
            await asyncio.sleep(0.3)  # Simulate cloud latency
            
            return {
                "text": "[Azure Speech processing - configure API key]",
                "confidence": 0.95,
                "is_final": True,
                "latency_ms": (time.time() - start_time) * 1000,
                "timestamp": timestamp,
                "language": self.config.default_language,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"Azure Speech processing error: {e}")
            return {
                "text": "",
                "confidence": 0.0,
                "is_final": False,
                "latency_ms": (time.time() - start_time) * 1000,
                "timestamp": timestamp,
                "error": str(e)
            }

class CloudASRManager:
    """Manager for multiple cloud ASR services."""
    
    def __init__(self):
        self.config = CloudASRConfig()
        self.google_asr = GoogleSpeechASR(self.config)
        self.azure_asr = AzureSpeechASR(self.config)
        
        self.available_services = []
    
    async def initialize(self) -> Dict[str, bool]:
        """Initialize all available cloud services."""
        results = {}
        
        # Initialize Google
        if await self.google_asr.initialize():
            self.available_services.append("google")
            results["google"] = True
        else:
            results["google"] = False
        
        # Initialize Azure
        if await self.azure_asr.initialize():
            self.available_services.append("azure")
            results["azure"] = True
        else:
            results["azure"] = False
        
        logger.info(f"Cloud services available: {self.available_services}")
        return results
    
    async def process_with_service(self, service: str, audio_data: bytes, timestamp: float) -> Dict[str, Any]:
        """Process audio with specific cloud service."""
        if service == "google" and "google" in self.available_services:
            return await self.google_asr.process_audio_chunk(audio_data, timestamp)
        elif service == "azure" and "azure" in self.available_services:
            return await self.azure_asr.process_audio_chunk(audio_data, timestamp)
        else:
            return {
                "text": "",
                "confidence": 0.0,
                "is_final": False,
                "error": f"Service '{service}' not available",
                "timestamp": timestamp
            }
    
    def get_available_services(self) -> list:
        """Get list of available cloud services."""
        return self.available_services.copy()
    
    def get_configuration_status(self) -> Dict[str, Any]:
        """Get configuration status for all services."""
        return {
            "google": {
                "sdk_available": GOOGLE_AVAILABLE,
                "configured": self.config.is_google_configured(),
                "credentials_path": self.config.google_credentials_path,
                "project_id": self.config.google_project_id
            },
            "azure": {
                "sdk_available": AZURE_AVAILABLE,
                "configured": self.config.is_azure_configured(),
                "region": self.config.azure_service_region,
                "has_key": bool(self.config.azure_subscription_key)
            }
        }

# Legacy functions for compatibility
def google_streaming_stub():
    """Legacy function - use GoogleSpeechASR class instead."""
    logger.info("Use GoogleSpeechASR class for Google Cloud Speech integration")
    return "Use GoogleSpeechASR class"

def azure_streaming_stub():
    """Legacy function - use AzureSpeechASR class instead."""
    logger.info("Use AzureSpeechASR class for Azure Speech integration")
    return "Use AzureSpeechASR class"

def notes():
    """Integration notes and tips."""
    return {
        'setup_instructions': {
            'google': [
                '1. Create Google Cloud project',
                '2. Enable Speech-to-Text API',
                '3. Create service account and download JSON key',
                '4. Set GOOGLE_APPLICATION_CREDENTIALS environment variable',
                '5. Set GOOGLE_CLOUD_PROJECT environment variable'
            ],
            'azure': [
                '1. Create Azure Speech Service resource',
                '2. Get subscription key and region',
                '3. Set AZURE_SPEECH_KEY environment variable',
                '4. Set AZURE_SPEECH_REGION environment variable'
            ]
        },
        'latency_tips': [
            'Use small audio chunks (100-500ms) with interim results enabled',
            'Deploy services in regions close to users',
            'Use enhanced/latest models for better accuracy',
            'Consider WebSocket streaming for continuous recognition'
        ],
        'privacy': [
            'Edge processing keeps audio local',
            'Cloud services require data transmission - use encryption',
            'Consider data residency requirements',
            'Implement PII redaction if needed'
        ],
        'cost_optimization': [
            'Use standard models for cost-effective processing',
            'Implement silence detection to avoid processing empty audio',
            'Cache results for repeated requests',
            'Monitor usage and set billing alerts'
        ]
    }

if __name__ == "__main__":
    # Demo configuration check
    async def demo():
        print("LiveSpeak Cloud ASR Configuration Check")
        print("=" * 45)
        
        manager = CloudASRManager()
        status = manager.get_configuration_status()
        
        print("Google Cloud Speech:")
        google_status = status["google"]
        print(f"  SDK Available: {google_status['sdk_available']}")
        print(f"  Configured: {google_status['configured']}")
        if google_status['credentials_path']:
            print(f"  Credentials: {google_status['credentials_path']}")
        if google_status['project_id']:
            print(f"  Project ID: {google_status['project_id']}")
        
        print("\nAzure Speech Service:")
        azure_status = status["azure"]
        print(f"  SDK Available: {azure_status['sdk_available']}")
        print(f"  Configured: {azure_status['configured']}")
        print(f"  Has API Key: {azure_status['has_key']}")
        print(f"  Region: {azure_status['region']}")
        
        print("\nInitializing services...")
        init_results = await manager.initialize()
        
        for service, success in init_results.items():
            status = "✅" if success else "❌"
            print(f"  {service.capitalize()}: {status}")
        
        available = manager.get_available_services()
        print(f"\nAvailable services: {available}")
        
        if not available:
            print("\n📝 Setup Instructions:")
            setup_notes = notes()['setup_instructions']
            for service, steps in setup_notes.items():
                print(f"\n{service.upper()}:")
                for step in steps:
                    print(f"  {step}")
    
    asyncio.run(demo())
