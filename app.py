import os
import uuid
import json
import logging
from typing import Dict
from fastapi import FastAPI, WebSocket, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from azure.communication.callautomation import (
    CallAutomationClient,
    CallInvite,
    PhoneNumberIdentifier,
    RecognizeInputType,
    TextSource,
    CallConnectionState,
)
from dotenv import load_dotenv
load_dotenv()

from agent_logic import VoiceAgent

# Configuration
ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING")
CALLBACK_URI_HOST = os.getenv("CALLBACK_URI_HOST")
ACS_PHONE_NUMBER = os.getenv("ACS_PHONE_NUMBER")
ACS_PHONE_NUMBER = os.getenv("ACS_PHONE_NUMBER")
TARGET_PHONE_NUMBER = os.getenv("TARGET_PHONE_NUMBER")

# Global var to store the dynamic caller for Inbound (MVP hack)
# In production, store this in VoiceAgent or DB.
INBOUND_CALLER = None

# Initialize Clients
acs_client = CallAutomationClient.from_connection_string(ACS_CONNECTION_STRING)
app = FastAPI()

# Enable CORS and Logging
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AgentT")

# DEBUG: Add file logging
try:
    fh = logging.FileHandler('debug_agent_v2.log')
    fh.setLevel(logging.INFO)
    logger.addHandler(fh)
except:
    pass

# State Management
call_agents: Dict[str, VoiceAgent] = {}
websockets: list[WebSocket] = []

class WebSocketManager:
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        websockets.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in websockets:
            websockets.remove(websocket)

    async def broadcast_transcript(self, message: str):
        for ws in websockets:
            try:
                await ws.send_json({"type": "transcript", "data": message})
            except Exception:
                pass
    
    async def request_pii(self, field: str):
        for ws in websockets:
            try:
                await ws.send_json({"type": "INPUT_NEEDED", "field": field})
            except Exception:
                pass

ws_manager = WebSocketManager()

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# Setup Templates
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data_text = await websocket.receive_text()
            try:
                data = json.loads(data_text)
                
                # Handle Human Input
                if data.get("type") == "input":
                    text_to_speak = data.get("data")
                    if call_agents and text_to_speak:
                        # Use the LATEST call (index -1) in case old ones weren't cleaned up yet
                        # Dictionaries preserve insertion order in modern Python
                        call_connection_id = list(call_agents.keys())[-1]
                        agent = call_agents[call_connection_id]
                        
                        logger.info(f"Human Input: {text_to_speak}")
                        agent.handle_human_input(text_to_speak)
                        
                        await play_to_call(call_connection_id, text_to_speak)
                        await ws_manager.broadcast_transcript(f"Agent: {text_to_speak}")

                # Handle PII Input (Legacy/PII specific)
                elif data.get("type") == "PII":
                     # ... (Keep existing if needed or just use input)
                     pass

            except json.JSONDecodeError:
                # Handle plain text input as fallback for legacy tests if any
                pass

    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
    finally:
        ws_manager.disconnect(websocket)

@app.post("/call")
async def initiate_call():
    """Start the call to the doctor's office."""
    target = PhoneNumberIdentifier(TARGET_PHONE_NUMBER)
    source = PhoneNumberIdentifier(ACS_PHONE_NUMBER)
    
    callback_uri = f"{CALLBACK_URI_HOST}/api/callbacks"
    
    call_invite = CallInvite(target=target, source_caller_id_number=source)
    
    logging.info(f"Initiating call to {TARGET_PHONE_NUMBER}...")
    
    result = acs_client.create_call(
        call_invite, 
        callback_url=callback_uri,
        cognitive_services_endpoint=os.getenv("AZURE_SPEECH_SERVICE_ENDPOINT")
        # Note: ACS usually needs a Cognitive Services resource for TTS/STT.
        # For simplicity we rely on default or configured in Azure.
    )
    
    logging.info(f"Call initiated. Connection ID: {result.call_connection_id}")
    
    # Initialize Agent
    call_agents[result.call_connection_id] = VoiceAgent(ws_manager)
    
    return {"call_connection_id": result.call_connection_id}

@app.post("/api/callbacks")
async def callback_handler(request: Request):
    """Handle ACS Webhooks."""
    global INBOUND_CALLER
    
    raw_json = await request.json()
    logger.info(f"Raw Webhook Payload: {json.dumps(raw_json)}")
    
    # Normalize to list
    if isinstance(raw_json, list):
        events = raw_json
    else:
        events = [raw_json]
    
    for event in events:
        # Get type safely (CloudEvent uses 'type', EventGrid uses 'eventType')
        event_type = event.get('type') or event.get('eventType')
        
        if event_type == 'Microsoft.EventGrid.SubscriptionValidationEvent':
            logger.info("Received Event Grid Validation Request")
            code = event['data']['validationCode']
            return {"validationResponse": code}

        if event_type == 'Microsoft.Communication.IncomingCall':
            logger.info("Received Incoming Call")
            incoming_call_context = event['data']['incomingCallContext']
            
            # Extract Caller ID (Source) to listen to them later
            try:
                logger.info(f"Full IncomingCall Data: {json.dumps(event['data'])}")
                src = event['data']['from']['phoneNumber']['value']
                INBOUND_CALLER = src
                # INBOUND_CALLER = src  <-- Removed duplicate
                logger.info(f"Inbound Caller stored: {INBOUND_CALLER}")
                print(f"\n📞 CALLER ID CAPTURED: {INBOUND_CALLER}\n") # User requested print
            except Exception as e:
                logger.error(f"Could not extract caller number from event: {e}")

            # Answer the call
            callback_uri = f"{CALLBACK_URI_HOST}/api/callbacks"
            
            # CRITICAL: Must provide Cognitive Services endpoint for STT/TTS
            # Separated from OpenAI Endpoint to avoid conflicts
            speech_endpoint = os.getenv("AZURE_SPEECH_SERVICE_ENDPOINT")
            if speech_endpoint and speech_endpoint.endswith('/'):
                speech_endpoint = speech_endpoint[:-1]
            
            # Additional Log to ensure we aren't passing None
            logger.info(f"Using Cognitive Services Endpoint (Speech): {speech_endpoint}")

            acs_client.answer_call(
                incoming_call_context=incoming_call_context, 
                callback_url=callback_uri,
                cognitive_services_endpoint=speech_endpoint
            )
            return {"status": "answering"}

        # Handle CloudEvent structure
        if 'callConnectionId' in event:
            call_connection_id = event['callConnectionId']
        elif 'data' in event and 'callConnectionId' in event['data']:
            call_connection_id = event['data']['callConnectionId']
        else:
            # IncomingCall and Validation don't have connection ID in the same way, handled above.
            # If we get here log and continue
            logger.warning(f"Could not find callConnectionId in event: {event['type']}")
            continue

        agent = call_agents.get(call_connection_id)
        
        # Create agent if new (e.g. for incoming call or if we missed creation)
        # For outbound, we created it in /call, but if server restarted, we lost memory.
        if not agent:
             logger.warning(f"Unknown call connection: {call_connection_id}. Re-creating agent.")
             # Simple recovery for demo
             call_agents[call_connection_id] = VoiceAgent(ws_manager)
             agent = call_agents[call_connection_id]

        if event['type'] == 'Microsoft.Communication.CallConnected':
            logger.info("Call Connected. Starting conversation...")
            await ws_manager.broadcast_transcript("System: Call Connected")
            
            # Ensure we know who we are talking to for recognition
            if not INBOUND_CALLER:
                logger.warning("INBOUND_CALLER missing. Attempting to extract from CallConnected event.")
                # log raw data to see what we have
                logger.info(f"DEBUG: CallConnected Event Data: {json.dumps(event)}")
                try:
                    # 'participants' is a list of dicts. We look for the PSTN user.
                    participants = event.get('data', {}).get('participants', [])
                    for p in participants:
                        if 'phoneNumber' in p.get('identifier', {}):
                            INBOUND_CALLER = p['identifier']['phoneNumber']['value']
                            logger.info(f"Recovered INBOUND_CALLER from CallConnected: {INBOUND_CALLER}")
                            break
                except Exception as e:
                    logger.error(f"Failed to extract caller from CallConnected: {e}")

            if not INBOUND_CALLER:
                 logger.error("CRITICAL: Could not determine remote participant. Recognition will likely fail.")
            else:
                 logger.info(f"Target Participant for Recognition: {INBOUND_CALLER}")

            # Start listing/speaking
            intro_text = "Hey You reached Agent T. What can I do for you?"
            await play_to_call(call_connection_id, intro_text)

        elif event['type'] == 'Microsoft.Communication.PlayCompleted':
            # Speech finished, start listening
            await start_recognition(call_connection_id)

        elif event['type'] == 'Microsoft.Communication.RecognizeCompleted':
            # STT finished
            data = event.get('data', {})
            if data.get('recognitionType') == 'speech':
               text = data['speechResult']['speech']
               logger.info(f"Recognized: {text}")
               
               # Process with Agent Logic
               action = await agent.process_audio_transcript(text)
               
               if action:
                   if action['type'] == 'SPEAK':
                       await play_to_call(call_connection_id, action['text'])
                   elif action['type'] == 'PII_REQUEST':
                       await ws_manager.request_pii(action['field'])
                       # Do NOT continue recognition loop or play anything. Wait for WS input.
                   elif action['type'] == 'HOLD':
                       # Wait loop
                       pass
               else:
                   # Action is None (Human in loop).
                   # We continue listening.
                   await start_recognition(call_connection_id)

        elif event['type'] == 'Microsoft.Communication.PlayFailed':
            logger.warning(f"Play Failed: {event.get('data')}")
            # Fallback: start listening so user call isn't dead
            await start_recognition(call_connection_id)

        elif event['type'] == 'Microsoft.Communication.RecognizeFailed':
            logger.error("Recognition Failed")
            # Retry or verify state
            await start_recognition(call_connection_id)
            
        elif event['type'] == 'Microsoft.Communication.CallDisconnected':
            logger.info(f"Call Disconnected: {call_connection_id}")
            await ws_manager.broadcast_transcript("System: Call Disconnected")
            # Cleanup
            if call_connection_id in call_agents:
                del call_agents[call_connection_id]
            
    return {"status": "ok"}

async def play_to_call(call_connection_id, text):
    try:
        call_connection = acs_client.get_call_connection(call_connection_id)
        text_source = TextSource(text=text, voice_name="en-US-AvaMultilingualNeural")
        call_connection.play_media(play_source=text_source)
    except Exception as e:
        logger.error(f"Failed to play media: {e}")

async def start_recognition(call_connection_id):
    try:
        call_connection = acs_client.get_call_connection(call_connection_id)
        
        # Determine who to listen to
        # If INBOUND_CALLER is set, use that. Else use TARGET_PHONE_NUMBER (outbound)
        target_phone = INBOUND_CALLER if INBOUND_CALLER else TARGET_PHONE_NUMBER
        
        logger.info(f"Starting recognition for: {target_phone}")

        call_connection.start_recognizing_media(
            input_type=RecognizeInputType.SPEECH,
            target_participant=PhoneNumberIdentifier(target_phone)
        )
    except Exception as e:
        logger.error(f"Failed to start recognition: {e}")
