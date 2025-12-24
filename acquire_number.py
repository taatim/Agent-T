import os
import time
from azure.communication.phonenumbers import (
    PhoneNumbersClient,
    PhoneNumberType,
    PhoneNumberAssignmentType,
    PhoneNumberCapabilityType,
    PhoneNumberCapabilities
)
from dotenv import load_dotenv

load_dotenv()
connection_string = os.getenv("ACS_CONNECTION_STRING")
client = PhoneNumbersClient.from_connection_string(connection_string)

def main():
    print("🔍 Searching for a local (Geographic) US number...")
    
    # Capabilities: We need outbound calling. Inbound is good too.
    capabilities = PhoneNumberCapabilities(
        calling=PhoneNumberCapabilityType.INBOUND_OUTBOUND,
        sms=PhoneNumberCapabilityType.NONE
    )
    
    # 1. Search
    try:
        # We try to find a number in US. 
        # Note: Some regions might not have straight US search without area code, but let's try.
        poller = client.begin_search_available_phone_numbers(
            country_code="US",
            phone_number_type=PhoneNumberType.GEOGRAPHIC,
            assignment_type=PhoneNumberAssignmentType.APPLICATION,
            capabilities=capabilities,
            quantity=1
        )
        search_result = poller.result()
    except Exception as e:
        print(f"❌ Search failed: {e}")
        return

    if not search_result.phone_numbers:
        print("❌ No numbers found.")
        return

    phone_number = search_result.phone_numbers[0]
    search_id = search_result.search_id
    print(f"✅ Found Number: {phone_number}")
    print(f"   Search ID: {search_id}")
    
    # 2. Purchase
    print("🛒 Purchasing number (this may take a minute)...")
    try:
        purchase_poller = client.begin_purchase_phone_numbers(search_id)
        purchase_poller.result() # Wait for completion
        print(f"🎉 Successfully purchased {phone_number}!")
        
        # 3. Update Environment
        # (We will output it for the agent to read and upadte)
        print(f"NEW_PHONE_NUMBER={phone_number}")
        
    except Exception as e:
        print(f"❌ Purchase failed: {e}")

if __name__ == "__main__":
    main()
