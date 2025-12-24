#!/bin/bash

# Configuration Script for Agent T
# Usage: ./configure.sh

echo "🔍  Agent T: Azure Auto-Configuration"
echo "======================================"

# 1. Check for Azure CLI
AZ_CMD="./.venv/bin/az"
if [ ! -f "$AZ_CMD" ]; then
    echo "❌  Error: Azure CLI not found in .venv."
    echo "    Please run 'uv pip install -r requirements.txt' first."
    exit 1
fi

echo "✅  Azure CLI found in .venv."

# 2. Check Login Status
echo "Checking Azure login status..."
$AZ_CMD account show &> /dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  Not logged in. Initiating login..."
    echo "❗ PLEASE CHECK THE OUPUT BELOW FOR A LOGIN CODE AND URL ❗"
    $AZ_CMD login --use-device-code
fi
echo "✅  Logged in."

# 3. Fetch ACS Connection String
echo "--------------------------------------"
echo "📡  Fetching Azure Communication Services details..."
RG_ACS="voicecallingRG"
echo "    Resource Group: $RG_ACS"

    # 3. Fetch ACS Connection String
echo "--------------------------------------"
echo "📡  Fetching Azure Communication Services details..."
RG_ACS="voicecallingRG"
echo "    Resource Group: $RG_ACS"

# Install extension if needed
echo "    Ensuring 'communication' extension is installed..."
$AZ_CMD extension add -n communication --yes &> /dev/null

# Find ACS Name
ACS_NAME=$($AZ_CMD communication list -g "$RG_ACS" --query "[0].name" -o tsv)

if [ -z "$ACS_NAME" ]; then
    echo "❌  No ACS resource found in '$RG_ACS'."
    echo "    Please check the resource group name."
else
    echo "    Found ACS Resource: $ACS_NAME"
    
    # Get Connection String
    # Note: CLI suggests 'list-key' instead of 'list-keys'
    ACS_CONN=$($AZ_CMD communication list-key --name "$ACS_NAME" -g "$RG_ACS" --query "primaryConnectionString" -o tsv)
    
    # Get Phone Number (First one found)
    ACS_PHONE=$($AZ_CMD communication phonenumber list --comm-svc-name "$ACS_NAME" -g "$RG_ACS" --query "[0].phoneNumber" -o tsv 2>/dev/null)
    
    echo "✅  Fetched Connection String."
    echo "    Phone Number: ${ACS_PHONE:-"None found"}"
fi

# 4. Fetch OpenAI Details
echo "--------------------------------------"
echo "🧠  Fetching Azure OpenAI details..."
echo "    Searching all resource groups for Cognitive Services/OpenAI..."

# Find OpenAI Account
AOAI_ID=$($AZ_CMD cognitiveservices account list --query "[?kind=='OpenAI'] | [0].id" -o tsv)

if [ -z "$AOAI_ID" ]; then
    echo "⚠️   No OpenAI resource found."
else
    AOAI_NAME=$(echo "$AOAI_ID" | rev | cut -d'/' -f1 | rev)
    AOAI_RG=$(echo "$AOAI_ID" | cut -d'/' -f5)
    
    echo "    Found OpenAI Resource: $AOAI_NAME (RG: $AOAI_RG)"
    
    # Get Endpoint (Use Name and RG, --ids failing)
    AOAI_ENDPOINT=$($AZ_CMD cognitiveservices account show -n "$AOAI_NAME" -g "$AOAI_RG" --query "properties.endpoint" -o tsv)
    
    # Get Key
    AOAI_KEY=$($AZ_CMD cognitiveservices account keys list -n "$AOAI_NAME" -g "$AOAI_RG" --query "key1" -o tsv)
    
    echo "✅  Fetched OpenAI Keys."
fi

# 5. Write to .env
echo "--------------------------------------"
echo "📝  Writing to .env..."

cat > .env <<EOF
ACS_CONNECTION_STRING="$ACS_CONN"
ACS_PHONE_NUMBER="$ACS_PHONE"
CALLBACK_URI_HOST="<REPLACE_WITH_NGROK_URL>"
TARGET_PHONE_NUMBER=""

AZURE_OPENAI_SERVICE_KEY="$AOAI_KEY"
AZURE_OPENAI_SERVICE_ENDPOINT="$AOAI_ENDPOINT"
AZURE_OPENAI_DEPLOYMENT_MODEL="gpt-4"

SPEECH_KEY=""
SPEECH_REGION=""
EOF

echo "✅  .env file created!"
echo "⚠️   ACTION REQUIRED: Edit .env to add:"
echo "    1. CALLBACK_URI_HOST (your ngrok URL)"
echo "    2. SPEECH_KEY/REGION (if not using OpenAI for everything)"
echo "    3. TARGET_PHONE_NUMBER"
