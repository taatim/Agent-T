import os
import json
import asyncio
from enum import Enum
from openai import AzureOpenAI
import logging

logger = logging.getLogger("AgentT")

import azure.cognitiveservices.speech as speechsdk

# Initialize Azure OpenAI
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_SERVICE_KEY"),
    api_version="2023-12-01-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_SERVICE_ENDPOINT")
)

DEPLOYMENT_MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT_MODEL", "gpt-4")

class AgentState(Enum):
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    PII_INPUT_NEEDED = "PII_INPUT_NEEDED"
    NEGOTIATING = "NEGOTIATING"
    HOLD = "HOLD"
    ESCALATING = "ESCALATING"
    FINISHED = "FINISHED"

class VoiceAgent:
    def __init__(self, websocket_manager):
        self.state = AgentState.LISTENING
        self.history = [
            {"role": "system", "content": (
                "You are Agent T, a medical appointment negotiator. "
                "Your goal is to get the earliest possible appointment for the user. "
                "You are speaking to a doctor's office receptionist or automated system. "
                "If the system or person asks for Personal Identifiable Information (PII) like Name, "
                "Date of Birth, or Address, you MUST output a JSON function call to 'request_pii'. "
                "Do NOT provide fake data. "
                "If you detect hold music or repetitive waiting messages, output 'HOLD_DETECTED'. "
                "If the automated system fails, request a Customer Service Representative."
            )}
        ]
        self.websocket_manager = websocket_manager
        self.latest_transcript = ""

    async def process_audio_transcript(self, text):
        """
        Process incoming Speech-to-Text transcript.
        HUMAN-IN-THE-LOOP MODE: Do not auto-respond.
        """
        if not text:
            return None

        self.latest_transcript = text
        await self.websocket_manager.broadcast_transcript(f"Remote: {text}")
        
        self.history.append({"role": "user", "content": text})
        
        # AUTO MODE: Generate AI Response
        response = self._get_llm_response_and_update_history()
        
        if response and response.get("type") == "SPEAK":
            await self.websocket_manager.broadcast_transcript(f"Agent: {response['text']}")
            
        return response

    def _get_llm_response_and_update_history(self):
        """
        Helper to get LLM response and update history.
        """
        response = self._get_llm_response()
        if response and response.get("type") == "SPEAK":
            self.history.append({"role": "assistant", "content": response["text"]})
        return response

    def handle_human_input(self, text):
        """Called when the human types a response in the web UI."""
        self.history.append({"role": "assistant", "content": text})
        return text

    def _get_llm_response(self):
        """
        Get response from Azure OpenAI.
        """
        try:
            logger.info(f"DEBUG: Generating LLM response...")
            logger.info(f"DEBUG: Endpoint: {os.getenv('AZURE_OPENAI_SERVICE_ENDPOINT')}")
            
            functions = [
                {
                    "name": "request_pii",
                    "description": "Request PII from the user via the frontend when the doctor asks for strictly personal info.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "field_name": {
                                "type": "string",
                                "description": "The specific PII field requested (e.g., 'Date of Birth', 'Address', 'Full Name')"
                            }
                        },
                        "required": ["field_name"]
                    }
                }
            ]

            completion = client.chat.completions.create(
                model=DEPLOYMENT_MODEL,
                messages=self.history,
                functions=functions,
                function_call="auto"
            )
            
            logger.info(f"DEBUG: Completion received: {completion}")

            message = completion.choices[0].message

            # Handle Function Calls (PII Request)
            if message.function_call:
                if message.function_call.name == "request_pii":
                    args = json.loads(message.function_call.arguments)
                    self.state = AgentState.PII_INPUT_NEEDED
                    return {"type": "PII_REQUEST", "field": args.get("field_name")}

            # Normal Text Response
            content = message.content
            if content:
                logger.info(f"DEBUG: LLM Content: {content}")
                if "HOLD_DETECTED" in content:
                    self.state = AgentState.HOLD
                    return {"type": "HOLD"}
                
                self.history.append({"role": "assistant", "content": content})
                return {"type": "SPEAK", "text": content}
            
            logger.info("DEBUG: No content in response")
            return None

        except Exception as e:
            logger.error(f"LLM Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def handle_user_pii_input(self, pii_text):
        """
        Received PII from frontend. Convert to audio immediately and return text to speak.
        Do NOT store in history long-term if strictly following "no storage", 
        but we need to speak it. 
        """
        # We don't verify or log this text.
        # We just return it to be spoken.
        # We implicitly assume the conversation flow continues after this.
        self.state = AgentState.NEGOTIATING
        return pii_text
