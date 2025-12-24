import os
from azure.communication.callautomation import (
    CallAutomationClient,
    CallInvite,
    PhoneNumberIdentifier
)
from dotenv import load_dotenv

load_dotenv()

connection_string = os.getenv("ACS_CONNECTION_STRING")
source_phone = os.getenv("ACS_PHONE_NUMBER")
target_phone = os.getenv("TARGET_PHONE_NUMBER")
callback_url = os.getenv("CALLBACK_URI_HOST") + "/api/callbacks"

print(f"Source: {source_phone}")
print(f"Target: {target_phone}")
print(f"Callback: {callback_url}")

from azure.communication.identity import CommunicationIdentityClient

client = CallAutomationClient.from_connection_string(connection_string)
identity_client = CommunicationIdentityClient.from_connection_string(connection_string)

print("Creating source user...")
user = identity_client.create_user()
print(f"User created: {user.properties['id']}")

print(f"Source: {repr(source_phone)}")
print(f"Target: {repr(target_phone)}")

target = PhoneNumberIdentifier(target_phone)
source = PhoneNumberIdentifier(source_phone.strip("+"))

# Try direct arguments matching signature
try:
    print("Initiating call (Direct Args)...")
    # Note: signature says target_participant. 
    result = client.create_call(
        target_participant=target,
        source_caller_id_number=source,
        callback_url=callback_url
    )
    print(f"Call initiated. ID: {result.call_connection_id}")
except Exception as e:
    print(f"Error: {e}")
