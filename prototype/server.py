"""LiveSpeak WebSocket Server - Real-time Speech-to-Text Processing.

This server implements the hybrid edge-cloud processing architecture,
handling real-time audio streams and providing intelligent transcription routing.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Set, Optional, Any
from pathlib import Path

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
    import tornado.web
    import tornado.httpserver
except ImportError as e:
    logging.error(f"Missing dependencies: {e}")
    logging.error("Install with: pip install websockets tornado")
    raise

from vosk_asr import VoskASR
from cloud_stub import google_streaming_stub, azure_streaming_stub

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LiveSpeakServer:
    """Main LiveSpeak server handling WebSocket connections and processing."""
    
    def __init__(self, host: str = "localhost", ws_port: int = 8765, http_port: int = 8080):
        self.host = host
        self.ws_port = ws_port
        self.http_port = http_port
        
        # Connected clients
        self.clients: Dict[str, WebSocketServerProtocol] = {}
        
        # Processing components
        self.edge_asr = VoskASR()
        
        # Configuration
        self.config = {
            "edge_enabled": True,
            "cloud_enabled": False,  # Disabled by default (needs API keys)
            "hybrid_mode": "edge_primary",
            "max_latency_ms": 1000,
            "chunk_size_ms": 300,
            "language": "en-US"
        }
        
        # Statistics
        self.stats = {
            "total_connections": 0,
            "active_connections": 0,
            "total_audio_chunks": 0,
            "total_transcriptions": 0,
            "avg_processing_time_ms": 0
        }
    
    async def initialize(self):
        """Initialize server components."""
        logger.info("Initializing LiveSpeak server...")
        
        # Initialize edge ASR
        if self.config["edge_enabled"]:
            edge_ready = await self.edge_asr.initialize()
            if not edge_ready:
                logger.warning("Edge ASR not available - cloud mode only")
                self.config["edge_enabled"] = False
        
        logger.info(f"Server initialized - Edge: {self.config['edge_enabled']}, Cloud: {self.config['cloud_enabled']}")
    
    async def handle_client(self, websocket: WebSocketServerProtocol, path: str):
        """Handle new WebSocket client connection."""
        client_id = str(uuid.uuid4())
        self.clients[client_id] = websocket
        self.stats["total_connections"] += 1
        self.stats["active_connections"] += 1
        
        logger.info(f"Client connected: {client_id} from {websocket.remote_address}")
        
        try:
            # Send initial configuration
            await self._send_message(websocket, {
                "type": "config",
                "client_id": client_id,
                "server_config": self.config,
                "supported_features": {
                    "edge_processing": self.config["edge_enabled"],
                    "cloud_processing": self.config["cloud_enabled"],
                    "real_time_streaming": True,
                    "partial_results": True
                }
            })
            
            # Handle client messages
            async for message in websocket:
                await self._handle_message(client_id, websocket, message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client disconnected: {client_id}")
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}")
        finally:
            # Cleanup
            if client_id in self.clients:
                del self.clients[client_id]
            self.stats["active_connections"] -= 1
    
    async def _handle_message(self, client_id: str, websocket: WebSocketServerProtocol, message: str):
        """Process incoming message from client."""
        try:
            data = json.loads(message) if isinstance(message, str) else message
            msg_type = data.get("type")
            
            if msg_type == "audio_chunk":
                await self._process_audio_chunk(client_id, websocket, data)
            elif msg_type == "config_update":
                await self._update_client_config(client_id, websocket, data)
            elif msg_type == "ping":
                await self._send_message(websocket, {"type": "pong", "timestamp": time.time()})
            else:
                logger.warning(f"Unknown message type from {client_id}: {msg_type}")
                
        except json.JSONDecodeError:
            # Handle binary audio data
            await self._process_raw_audio(client_id, websocket, message)
        except Exception as e:
            logger.error(f"Error processing message from {client_id}: {e}")
    
    async def _process_audio_chunk(self, client_id: str, websocket: WebSocketServerProtocol, data: Dict[str, Any]):
        """Process audio chunk with hybrid processing."""
        try:
            audio_data = bytes.fromhex(data.get("audio_data", ""))
            timestamp = data.get("timestamp", time.time())
            chunk_id = data.get("chunk_id", str(uuid.uuid4()))
            
            self.stats["total_audio_chunks"] += 1
            
            # Hybrid processing decision
            processing_mode = self._decide_processing_mode(client_id, data)
            
            results = []
            
            # Edge processing
            if processing_mode in ["edge_only", "edge_primary", "parallel"]:
                if self.config["edge_enabled"]:
                    edge_result = await self._process_with_edge(audio_data, timestamp)
                    edge_result["source"] = "edge"
                    edge_result["chunk_id"] = chunk_id
                    results.append(edge_result)
            
            # Cloud processing (placeholder - would need API keys)
            if processing_mode in ["cloud_only", "cloud_primary", "parallel"]:
                if self.config["cloud_enabled"]:
                    cloud_result = await self._process_with_cloud(audio_data, timestamp)
                    cloud_result["source"] = "cloud"
                    cloud_result["chunk_id"] = chunk_id
                    results.append(cloud_result)
            
            # Send results to client
            for result in results:
                await self._send_message(websocket, {
                    "type": "transcription",
                    "client_id": client_id,
                    "result": result,
                    "processing_mode": processing_mode,
                    "timestamp": timestamp
                })
                
            self.stats["total_transcriptions"] += len(results)
            
        except Exception as e:
            logger.error(f"Error processing audio chunk from {client_id}: {e}")
            await self._send_message(websocket, {
                "type": "error",
                "message": f"Audio processing error: {str(e)}",
                "timestamp": time.time()
            })
    
    def _decide_processing_mode(self, client_id: str, data: Dict[str, Any]) -> str:
        """Decide whether to use edge, cloud, or hybrid processing."""
        # Simple decision logic - can be enhanced with ML
        network_quality = data.get("network_quality", 1.0)
        privacy_mode = data.get("privacy_mode", False)
        
        if privacy_mode or network_quality < 0.3:
            return "edge_only"
        elif not self.config["edge_enabled"]:
            return "cloud_only"
        elif network_quality > 0.8 and self.config["cloud_enabled"]:
            return "parallel"
        else:
            return "edge_primary"
    
    async def _process_with_edge(self, audio_data: bytes, timestamp: float) -> Dict[str, Any]:
        """Process audio with edge ASR."""
        start_time = time.time()
        
        try:
            result = self.edge_asr.process_audio_chunk(audio_data)
            result["latency_ms"] = (time.time() - start_time) * 1000
            result["timestamp"] = timestamp
            return result
            
        except Exception as e:
            logger.error(f"Edge processing error: {e}")
            return {
                "text": "",
                "confidence": 0.0,
                "is_final": False,
                "error": str(e),
                "latency_ms": (time.time() - start_time) * 1000,
                "timestamp": timestamp
            }
    
    async def _process_with_cloud(self, audio_data: bytes, timestamp: float) -> Dict[str, Any]:
        """Process audio with cloud ASR (placeholder)."""
        start_time = time.time()
        
        # Placeholder - would integrate with actual cloud APIs
        await asyncio.sleep(0.3)  # Simulate cloud latency
        
        return {
            "text": "[Cloud processing not configured]",
            "confidence": 0.0,
            "is_final": True,
            "latency_ms": (time.time() - start_time) * 1000,
            "timestamp": timestamp,
            "note": "Configure API keys in cloud_stub.py for cloud processing"
        }
    
    async def _process_raw_audio(self, client_id: str, websocket: WebSocketServerProtocol, audio_data: bytes):
        """Process raw binary audio data."""
        # Handle raw audio stream
        chunk_data = {
            "audio_data": audio_data.hex(),
            "timestamp": time.time(),
            "chunk_id": str(uuid.uuid4())
        }
        await self._process_audio_chunk(client_id, websocket, chunk_data)
    
    async def _send_message(self, websocket: WebSocketServerProtocol, message: Dict[str, Any]):
        """Send JSON message to client."""
        try:
            await websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending message: {e}")
    
    async def _update_client_config(self, client_id: str, websocket: WebSocketServerProtocol, data: Dict[str, Any]):
        """Update client-specific configuration."""
        # Handle client configuration updates
        config_updates = data.get("config", {})
        logger.info(f"Config update from {client_id}: {config_updates}")
        
        await self._send_message(websocket, {
            "type": "config_updated",
            "message": "Configuration updated successfully"
        })
    
    def get_status(self) -> Dict[str, Any]:
        """Get server status and statistics."""
        return {
            "server_info": {
                "host": self.host,
                "ws_port": self.ws_port,
                "http_port": self.http_port,
                "uptime_seconds": time.time() - getattr(self, 'start_time', time.time())
            },
            "config": self.config,
            "stats": self.stats,
            "edge_asr_stats": self.edge_asr.get_performance_stats() if self.edge_asr else None
        }

class HTTPHandler(tornado.web.RequestHandler):
    """HTTP endpoint for server status and web interface."""
    
    def initialize(self, server_instance):
        self.server = server_instance
    
    def get(self, path=None):
        if path == "status":
            self.write(self.server.get_status())
        elif path == "stats":
            self.write(self.server.stats)
        else:
            # Serve web interface
            self.write(self._get_web_interface())
    
    def _get_web_interface(self) -> str:
        """Simple web interface for testing."""
        return """
<!DOCTYPE html>
<html>
<head>
    <title>LiveSpeak - Real-time Captioning</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { 
            max-width: 900px; margin: 0 auto; 
            background: rgba(255, 255, 255, 0.95); 
            backdrop-filter: blur(10px);
            border-radius: 20px; 
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header { 
            background: linear-gradient(135deg, #007acc, #0056a3);
            color: white; text-align: center; 
            padding: 30px; margin-bottom: 0;
        }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; font-weight: 300; }
        .header p { opacity: 0.9; font-size: 1.1em; }
        
        .dashboard { padding: 30px; }
        
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .status-card { 
            background: #f8f9ff; 
            padding: 20px; 
            border-radius: 12px; 
            border-left: 4px solid #007acc;
            transition: transform 0.2s ease;
        }
        .status-card:hover { transform: translateY(-2px); }
        .status-label { font-weight: 600; color: #555; margin-bottom: 8px; }
        .status-value { font-size: 1.2em; color: #007acc; font-weight: 500; }
        
        .controls { 
            display: flex;
            gap: 15px;
            justify-content: center;
            margin: 30px 0;
            flex-wrap: wrap;
        }
        .btn { 
            background: linear-gradient(135deg, #007acc, #0056a3);
            color: white; border: none; 
            padding: 15px 30px; 
            border-radius: 25px;
            cursor: pointer; 
            font-size: 16px;
            font-weight: 500;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(0, 122, 204, 0.3);
        }
        .btn:hover { 
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 122, 204, 0.4);
        }
        .btn:disabled { 
            background: #ddd; 
            cursor: not-allowed; 
            transform: none;
            box-shadow: none;
        }
        .btn-danger { 
            background: linear-gradient(135deg, #ff6b6b, #ee5a24);
            box-shadow: 0 4px 15px rgba(255, 107, 107, 0.3);
        }
        .btn-danger:hover { 
            box-shadow: 0 8px 25px rgba(255, 107, 107, 0.4);
        }
        
        .captions-container {
            background: #fff;
            border: 2px solid #e9ecef;
            border-radius: 12px;
            min-height: 300px;
            position: relative;
            overflow: hidden;
        }
        .captions-header {
            background: #f8f9fa;
            padding: 15px 20px;
            border-bottom: 1px solid #e9ecef;
            font-weight: 600;
            color: #495057;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .captions { 
            padding: 20px; 
            max-height: 400px; 
            overflow-y: auto;
            font-size: 16px;
            line-height: 1.6;
        }
        .captions::-webkit-scrollbar { width: 6px; }
        .captions::-webkit-scrollbar-track { background: #f1f1f1; border-radius: 3px; }
        .captions::-webkit-scrollbar-thumb { background: #007acc; border-radius: 3px; }
        
        .transcription { 
            margin: 10px 0; 
            padding: 12px 16px;
            border-radius: 8px;
            animation: fadeIn 0.5s ease;
        }
        .transcription.final { 
            background: #e8f5e8; 
            border-left: 4px solid #28a745;
        }
        .transcription.interim { 
            background: #fff3cd; 
            border-left: 4px solid #ffc107;
            opacity: 0.8;
        }
        .source-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
            margin-right: 10px;
        }
        .source-edge { background: #e3f2fd; color: #1976d2; }
        .source-cloud { background: #e8f5e8; color: #388e3c; }
        
        .placeholder { 
            text-align: center; 
            color: #6c757d; 
            margin: 40px 0;
        }
        .placeholder-icon { font-size: 48px; margin-bottom: 15px; opacity: 0.5; }
        
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .recording { animation: pulse 1.5s infinite; }
        
        @media (max-width: 768px) {
            .container { margin: 10px; border-radius: 15px; }
            .header { padding: 20px; }
            .header h1 { font-size: 2em; }
            .dashboard { padding: 20px; }
            .status-grid { grid-template-columns: 1fr; }
            .controls { flex-direction: column; align-items: center; }
            .btn { width: 200px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎤 LiveSpeak</h1>
            <p>Real-time Speech-to-Text with Hybrid Edge-Cloud Processing</p>
        </div>
        
        <div class="dashboard">
            <div class="status-grid">
                <div class="status-card">
                    <div class="status-label">Connection Status</div>
                    <div class="status-value" id="connection-status">Disconnected</div>
                </div>
                <div class="status-card">
                    <div class="status-label">Processing Mode</div>
                    <div class="status-value" id="processing-mode">Edge-Primary</div>
                </div>
                <div class="status-card">
                    <div class="status-label">Response Latency</div>
                    <div class="status-value" id="latency">-- ms</div>
                </div>
                <div class="status-card">
                    <div class="status-label">Audio Chunks</div>
                    <div class="status-value" id="chunks-count">0</div>
                </div>
            </div>
            
            <div class="controls">
                <button class="btn" id="connect-btn" onclick="connect()">🔌 Connect</button>
                <button class="btn" id="start-btn" onclick="startRecording()" disabled>🎙️ Start Recording</button>
                <button class="btn btn-danger" id="stop-btn" onclick="stopRecording()" disabled>⏹️ Stop Recording</button>
            </div>
            
            <div class="captions-container">
                <div class="captions-header">
                    <span>Live Transcription</span>
                    <span id="recording-indicator" style="display: none;">🔴 Recording...</span>
                </div>
                <div class="captions" id="captions">
                    <div class="placeholder">
                        <div class="placeholder-icon">🎯</div>
                        <p>Click "Connect" then "Start Recording" to begin live transcription</p>
                        <p style="margin-top: 10px; font-size: 14px; opacity: 0.7;">Your voice will be transcribed in real-time using edge processing</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let audioStream = null;
        let chunksProcessed = 0;
        
        function connect() {
            const wsUrl = `ws://${window.location.hostname}:8765`;
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => {
                document.getElementById('connection-status').textContent = '🟢 Connected';
                document.getElementById('connect-btn').disabled = true;
                document.getElementById('start-btn').disabled = false;
                addStatusMessage('Connected to LiveSpeak server', 'success');
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleServerMessage(data);
            };
            
            ws.onclose = () => {
                document.getElementById('connection-status').textContent = '🔴 Disconnected';
                document.getElementById('connect-btn').disabled = false;
                document.getElementById('start-btn').disabled = true;
                document.getElementById('stop-btn').disabled = true;
                hideRecordingIndicator();
            };
            
            ws.onerror = () => {
                addStatusMessage('Connection error. Please check server.', 'error');
            };
        }
        
        function handleServerMessage(data) {
            if (data.type === 'transcription') {
                const result = data.result;
                if (result.text && result.text.trim()) {
                    addTranscription(result.text, result.source, result.is_final);
                    document.getElementById('latency').textContent = `${result.latency_ms?.toFixed(0) || '--'} ms`;
                    chunksProcessed++;
                    document.getElementById('chunks-count').textContent = chunksProcessed;
                }
            } else if (data.type === 'config') {
                const mode = data.server_config.edge_enabled ? '⚡ Edge-Primary' : '☁️ Cloud-Only';
                document.getElementById('processing-mode').textContent = mode;
            }
        }
        
        async function startRecording() {
            try {
                // Clear previous transcriptions when starting new session
                clearTranscriptions();
                chunksProcessed = 0;
                document.getElementById('chunks-count').textContent = '0';
                
                audioStream = await navigator.mediaDevices.getUserMedia({ 
                    audio: {
                        sampleRate: 16000,
                        channelCount: 1,
                        echoCancellation: true,
                        noiseSuppression: true
                    }
                });
                
                // Create AudioContext for raw audio processing
                const audioContext = new (window.AudioContext || window.webkitAudioContext)({
                    sampleRate: 16000
                });
                
                const source = audioContext.createMediaStreamSource(audioStream);
                const processor = audioContext.createScriptProcessor(4096, 1, 1);
                
                processor.onaudioprocess = (event) => {
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        const inputBuffer = event.inputBuffer;
                        const inputData = inputBuffer.getChannelData(0);
                        
                        // Convert float32 to int16
                        const int16Data = new Int16Array(inputData.length);
                        for (let i = 0; i < inputData.length; i++) {
                            const sample = Math.max(-1, Math.min(1, inputData[i]));
                            int16Data[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
                        }
                        
                        // Convert to hex string
                        const hexString = Array.from(new Uint8Array(int16Data.buffer))
                            .map(byte => byte.toString(16).padStart(2, '0'))
                            .join('');
                        
                        ws.send(JSON.stringify({
                            type: 'audio_chunk',
                            audio_data: hexString,
                            timestamp: Date.now() / 1000,
                            chunk_id: Math.random().toString(36).substr(2, 9),
                            sample_rate: 16000,
                            channels: 1,
                            format: 'int16'
                        }));
                    }
                };
                
                source.connect(processor);
                processor.connect(audioContext.destination);
                
                // Store references for cleanup
                window.audioContext = audioContext;
                window.processor = processor;
                window.source = source;
                
                document.getElementById('start-btn').disabled = true;
                document.getElementById('stop-btn').disabled = false;
                showRecordingIndicator();
                addStatusMessage('🎙️ Recording started - speak now!', 'success');
                
            } catch (error) {
                addStatusMessage(`❌ Microphone error: ${error.message}`, 'error');
                console.error('Audio setup error:', error);
            }
        }
        
        function stopRecording() {
            if (window.audioContext) {
                window.processor.disconnect();
                window.source.disconnect();
                window.audioContext.close();
                window.audioContext = null;
                window.processor = null;
                window.source = null;
            }
            
            if (audioStream) {
                audioStream.getTracks().forEach(track => track.stop());
                audioStream = null;
            }
            
            document.getElementById('start-btn').disabled = false;
            document.getElementById('stop-btn').disabled = true;
            hideRecordingIndicator();
            addStatusMessage('⏹️ Recording stopped', 'info');
        }
        
        function showRecordingIndicator() {
            const indicator = document.getElementById('recording-indicator');
            indicator.style.display = 'block';
            document.getElementById('stop-btn').classList.add('recording');
        }
        
        function hideRecordingIndicator() {
            const indicator = document.getElementById('recording-indicator');
            indicator.style.display = 'none';
            document.getElementById('stop-btn').classList.remove('recording');
        }
        
        function addTranscription(text, source, isFinal) {
            const captions = document.getElementById('captions');
            
            // Remove placeholder if it exists
            const placeholder = captions.querySelector('.placeholder');
            if (placeholder) {
                placeholder.remove();
            }
            
            const div = document.createElement('div');
            div.className = `transcription ${isFinal ? 'final' : 'interim'}`;
            
            const sourceBadge = source === 'edge' ? 
                '<span class="source-badge source-edge">⚡ Edge</span>' : 
                '<span class="source-badge source-cloud">☁️ Cloud</span>';
            
            div.innerHTML = `${sourceBadge}${text}`;
            
            captions.appendChild(div);
            captions.scrollTop = captions.scrollHeight;
            
            // Auto-remove interim results after 5 seconds to keep UI clean
            if (!isFinal) {
                setTimeout(() => {
                    if (div.parentNode && div.classList.contains('interim')) {
                        div.remove();
                    }
                }, 5000);
            }
        }
        
        function addStatusMessage(message, type) {
            const captions = document.getElementById('captions');
            const div = document.createElement('div');
            div.className = 'transcription interim';
            div.innerHTML = `<span class="source-badge" style="background: #e9ecef; color: #495057;">ℹ️ System</span>${message}`;
            
            captions.appendChild(div);
            captions.scrollTop = captions.scrollHeight;
            
            // Auto-remove status messages after 3 seconds
            setTimeout(() => {
                if (div.parentNode) {
                    div.remove();
                }
            }, 3000);
        }
        
        function clearTranscriptions() {
            const captions = document.getElementById('captions');
            captions.innerHTML = '';
        }
    </script>
</body>
</html>
        """

async def start_server():
    """Start the LiveSpeak server with WebSocket and HTTP endpoints."""
    server = LiveSpeakServer()
    server.start_time = time.time()
    
    await server.initialize()
    
    # Create WebSocket handler wrapper
    async def websocket_handler(websocket, path=None):
        """WebSocket connection handler wrapper."""
        # Handle both old and new websockets library calling patterns
        if path is None:
            path = "/"
        await server.handle_client(websocket, path)
    
    # Start WebSocket server
    logger.info(f"Starting WebSocket server on {server.host}:{server.ws_port}")
    ws_server = websockets.serve(websocket_handler, server.host, server.ws_port)
    
    # Start HTTP server for web interface
    app = tornado.web.Application([
        (r"/(.*)", HTTPHandler, {"server_instance": server}),
    ])
    
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(server.http_port)
    logger.info(f"Starting HTTP server on {server.host}:{server.http_port}")
    
    logger.info("LiveSpeak server started successfully!")
    logger.info(f"Web interface: http://{server.host}:{server.http_port}")
    logger.info(f"WebSocket endpoint: ws://{server.host}:{server.ws_port}")
    
    # Run both servers
    await asyncio.gather(
        ws_server,
        asyncio.Event().wait()  # Run forever
    )

if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise