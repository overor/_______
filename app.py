import gradio as gr
import random
import time
import datetime
import json
import re
from typing import Dict, List, Tuple, Optional

# JavaScript code for Transformers.js speech processing
transformers_js_code = """
<script src="https://cdn.jsdelivr.net/npm/@xenova/transformers@2.6.1"></script>
<script>
// Initialize Transformers.js pipelines
let sttPipeline = null;
let ttsPipeline = null;
let speakerEmbeddings = null;

// Load models asynchronously
async function loadModels() {
    try {
        // Show loading status
        document.getElementById("status-text").innerText = "Loading speech models...";
        
        // Load speech-to-text model
        const { pipeline } = await import('https://cdn.jsdelivr.net/npm/@xenova/transformers@2.6.1');
        sttPipeline = await pipeline('automatic-speech-recognition', 'Xenova/whisper-tiny');
        
        // Load text-to-speech model and embeddings
        ttsPipeline = await pipeline('text-to-speech', 'Xenova/speecht5_tts');
        const { loadSpeakerEmbeddings } = await import('https://cdn.jsdelivr.net/npm/@xenova/transformers@2.6.1');
        speakerEmbeddings = await loadSpeakerEmbeddings('Xenova/speecht5_vc_pt_sd_epoch_1000');
        
        console.log('All models loaded successfully');
        document.getElementById("status-text").innerText = "Ready to listen";
    } catch (error) {
        console.error('Error loading models:', error);
        document.getElementById("status-text").innerText = "Error loading models";
    }
}

// Transcribe audio using Transformers.js
async function transcribeAudio(audioBlob) {
    if (!sttPipeline) {
        console.error('Speech-to-text model not loaded');
        return "Speech recognition not ready";
    }
    
    try {
        document.getElementById("status-text").innerText = "Processing speech...";
        const output = await sttPipeline(audioBlob, {
            language: 'english',
            task: 'transcribe',
        });
        document.getElementById("status-text").innerText = "Ready to listen";
        return output.text;
    } catch (error) {
        console.error('Transcription error:', error);
        document.getElementById("status-text").innerText = "Ready to listen";
        return "I couldn't understand that";
    }
}

// Generate speech using Transformers.js
async function generateSpeech(text) {
    if (!ttsPipeline || !speakerEmbeddings) {
        console.error('Text-to-speech model not loaded');
        return null;
    }
    
    try {
        const audio = await ttsPipeline(text, {
            speaker_embeddings: speakerEmbeddings,
        });
        return URL.createObjectURL(audio);
    } catch (error) {
        console.error('Speech generation error:', error);
        return null;
    }
}

// Initialize models when page loads
window.addEventListener('DOMContentLoaded', () => {
    loadModels();
    console.log('Transformers.js initialized');
});

// Function to handle audio recording and transcription
async function handleAudioRecording(audioBlob) {
    const transcript = await transcribeAudio(audioBlob);
    if (transcript && transcript !== "I couldn't understand that") {
        // Send the transcript to Gradio
        const hiddenTextbox = document.querySelector('#hidden-transcript textarea');
        if (hiddenTextbox) {
            hiddenTextbox.value = transcript;
            hiddenTextbox.dispatchEvent(new Event('input', { bubbles: true }));
            hiddenTextbox.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }
}

// Function to speak text
async function speakText(text) {
    const audioUrl = await generateSpeech(text);
    if (audioUrl) {
        const audio = new Audio(audioUrl);
        audio.play();
    }
}

// Add event listener for when the bot response updates
function setupResponseObserver() {
    const targetNode = document.querySelector('#ai-response textarea');
    if (targetNode) {
        const config = { characterData: true, childList: true, subtree: true };
        const callback = function(mutationsList, observer) {
            for (const mutation of mutationsList) {
                if (mutation.type === 'childList' || mutation.type === 'characterData') {
                    const responseText = targetNode.value;
                    if (responseText && !responseText.includes('Hello! I\'m your AppleCare concierge')) {
                        speakText(responseText);
                    }
                }
            }
        };
        const observer = new MutationObserver(callback);
        observer.observe(targetNode, config);
    }
}

// Initialize when page loads
window.addEventListener('DOMContentLoaded', () => {
    loadModels();
    setTimeout(setupResponseObserver, 2000); // Wait for Gradio to render
});
</script>
"""

class AppleCareVoiceConcierge:
    def __init__(self):
        self.conversation_state = {
            "step": "greeting",
            "device": None,
            "issue": None,
            "location": None,
            "imei": None,
            "user_name": None,
            "estimated_cost": None,
            "nearest_store": None,
            "history": []
        }

        # Store locations database
        self.stores = {
            "10001": {"name": "Apple Fifth Avenue", "address": "767 5th Ave, New York, NY 10153", "phone": "(212) 336-1440"},
            "10029": {"name": "Apple Upper East Side", "address": "940 Madison Ave, New York, NY 10075", "phone": "(212) 284-1800"},
            "90210": {"name": "Apple Beverly Hills", "address": "444 N Rodeo Dr, Beverly Hills, CA 90210", "phone": "(310) 273-3000"},
            "94102": {"name": "Apple Union Square", "address": "300 Post St, San Francisco, CA 94108", "phone": "(415) 392-0202"},
            "60611": {"name": "Apple Michigan Avenue", "address": "401 N Michigan Ave, Chicago, IL 60611", "phone": "(312) 981-4104"},
            "75201": {"name": "Apple Northpark Center", "address": "8687 N Central Expy, Dallas, TX 75225", "phone": "(214) 965-0960"},
            "02116": {"name": "Apple Boylston Street", "address": "815 Boylston St, Boston, MA 02116", "phone": "(617) 385-9400"},
            "98101": {"name": "Apple University Village", "address": "4742 42nd Ave NE, Seattle, WA 98105", "phone": "(206) 892-0076"},
            "33139": {"name": "Apple Lincoln Road", "address": "1021 Lincoln Rd, Miami Beach, FL 33139", "phone": "(305) 421-0200"},
            "30309": {"name": "Apple Lenox Square", "address": "3393 Peachtree Rd NE, Atlanta, GA 30326", "phone": "(404) 816-9500"}
        }
        
        # City mappings
        self.city_mappings = {
            "new york": "10001",
            "nyc": "10001",
            "manhattan": "10001",
            "los angeles": "90210",
            "la": "90210",
            "beverly hills": "90210",
            "san francisco": "94102",
            "sf": "94102",
            "chicago": "60611",
            "dallas": "75201",
            "boston": "02116",
            "seattle": "98101",
            "miami": "33139",
            "atlanta": "30309"
        }
        
        # Repair costs
        self.repair_costs = {
            "iphone": {
                "screen": "$279",
                "battery": "$89",
                "camera": "$149",
                "water": "$99 diagnostic + repair cost",
                "speaker": "$169",
                "charging": "$99"
            },
            "ipad": {
                "screen": "$399",
                "battery": "$129",
                "camera": "$199",
                "water": "$149 diagnostic + repair cost",
                "speaker": "$149",
                "charging": "$149"
            },
            "mac": {
                "screen": "$599",
                "battery": "$199",
                "keyboard": "$249",
                "trackpad": "$179",
                "water": "$299 diagnostic + repair cost"
            },
            "watch": {
                "screen": "$249",
                "battery": "$79",
                "water": "$229 service exchange"
            }
        }

    def reset_conversation(self):
        """Reset conversation state"""
        self.conversation_state = {
            "step": "greeting",
            "device": None,
            "issue": None,
            "location": None,
            "imei": None,
            "user_name": None,
            "estimated_cost": None,
            "nearest_store": None,
            "history": []
        }

    def extract_device_info(self, text: str) -> Optional[str]:
        """Extract device type from user input"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["iphone", "phone"]):
            return "iphone"
        elif any(word in text_lower for word in ["ipad", "tablet"]):
            return "ipad"
        elif any(word in text_lower for word in ["mac", "macbook", "laptop", "computer", "imac"]):
            return "mac"
        elif any(word in text_lower for word in ["watch", "apple watch"]):
            return "watch"
        return None

    def extract_issue_info(self, text: str, device: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract issue type and cost from user input"""
        text_lower = text.lower()
        
        issue_keywords = {
            "screen": ["screen", "crack", "broken", "display", "shatter"],
            "battery": ["battery", "charge", "power", "drain", "dead"],
            "camera": ["camera", "photo", "lens", "focus"],
            "water": ["water", "wet", "liquid", "rain", "drop", "spill"],
            "speaker": ["speaker", "sound", "audio", "volume"],
            "charging": ["charging", "port", "cable", "connector"],
            "keyboard": ["keyboard", "key", "typing"],
            "trackpad": ["trackpad", "mouse", "cursor", "click"]
        }
        
        for issue_type, keywords in issue_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                if device in self.repair_costs and issue_type in self.repair_costs[device]:
                    return issue_type, self.repair_costs[device][issue_type]
        
        return None, None

    def extract_location_info(self, text: str) -> Optional[Dict]:
        """Extract location from user input"""
        text_lower = text.lower()
        
        # Check for ZIP codes
        zip_match = re.search(r'\b\d{5}\b', text)
        if zip_match:
            zip_code = zip_match.group()
            if zip_code in self.stores:
                return self.stores[zip_code]
            else:
                return self.stores["10001"]  # Default to NYC
        
        # Check for city names
        for city, zip_code in self.city_mappings.items():
            if city in text_lower:
                return self.stores[zip_code]
        
        return None

    def extract_imei(self, text: str) -> Optional[str]:
        """Extract IMEI or serial number from user input"""
        # Look for sequences of alphanumeric characters (10+ chars)
        imei_match = re.search(r'\b[A-Za-z0-9]{10,}\b', text.replace(" ", ""))
        if imei_match:
            return imei_match.group()
        return None

    def generate_appointment_details(self) -> Dict:
        """Generate realistic appointment details"""
        # Generate appointment for next business day
        tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
        if tomorrow.weekday() >= 5:  # Weekend
            tomorrow += datetime.timedelta(days=(7 - tomorrow.weekday()))
        
        # Available time slots
        time_slots = ["9:00 AM", "10:30 AM", "12:00 PM", "1:30 PM", "3:00 PM", "4:30 PM"]
        selected_time = random.choice(time_slots)
        
        # Generate confirmation number
        confirmation = "AC" + "".join(random.choices("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=6))
        
        return {
            "date": tomorrow.strftime("%A, %B %d, %Y"),
            "time": selected_time,
            "confirmation": confirmation
        }

    def process_conversation(self, user_input: str) -> str:
        """Main conversation processing logic"""
        if not user_input.strip():
            return "I didn't catch that. Could you please speak again?"
        
        # Add to history
        self.conversation_state["history"].append({"role": "user", "content": user_input})
        
        current_step = self.conversation_state["step"]
        
        if current_step == "greeting":
            # Extract device information
            device = self.extract_device_info(user_input)
            if device:
                self.conversation_state["device"] = device
                self.conversation_state["step"] = "issue_identification"
                device_name = device.title() if device != "iphone" else "iPhone"
                if device == "mac":
                    device_name = "Mac"
                response = f"I can help with your {device_name}. What seems to be the problem? For example, is the screen damaged, battery issues, or something else?"
            else:
                response = "I can help with iPhone, iPad, Mac, or Apple Watch repairs. Which device needs assistance today?"
        
        elif current_step == "issue_identification":
            # Extract issue information
            issue_type, cost = self.extract_issue_info(user_input, self.conversation_state["device"])
            if issue_type and cost:
                self.conversation_state["issue"] = issue_type
                self.conversation_state["estimated_cost"] = cost
                self.conversation_state["step"] = "location_gathering"
                device_name = self.conversation_state["device"].title()
                if self.conversation_state["device"] == "iphone":
                    device_name = "iPhone"
                elif self.conversation_state["device"] == "mac":
                    device_name = "Mac"
                response = f"I understand you need {issue_type} repair for your {device_name}. The estimated cost is {cost}. To find the nearest Apple Store, could you tell me your ZIP code or city?"
            else:
                response = "Could you describe the issue in more detail? For example, is it a cracked screen, battery problem, water damage, or something else?"
        
        elif current_step == "location_gathering":
            # Extract location information
            store_info = self.extract_location_info(user_input)
            if store_info:
                self.conversation_state["nearest_store"] = store_info
                self.conversation_state["step"] = "imei_gathering"
                response = f"Perfect! The nearest Apple Store is {store_info['name']} at {store_info['address']}. For the appointment, I'll need your device's IMEI or serial number. You can find this in Settings > General > About, or you can say 'skip' if you don't have it available."
            else:
                response = "I need your location to find the nearest Apple Store. Could you please provide your ZIP code or city name?"
        
        elif current_step == "imei_gathering":
            if "skip" in user_input.lower():
                self.conversation_state["imei"] = "Will verify at appointment"
            else:
                imei = self.extract_imei(user_input)
                self.conversation_state["imei"] = imei if imei else "Will verify at appointment"
            
            self.conversation_state["step"] = "confirmation"
            device_name = self.conversation_state["device"].title()
            if self.conversation_state["device"] == "iphone":
                device_name = "iPhone"
            elif self.conversation_state["device"] == "mac":
                device_name = "Mac"
            
            response = f"""Let me confirm your repair appointment:

📱 Device: {device_name}
🔧 Issue: {self.conversation_state["issue"].title()} repair
💰 Estimated Cost: {self.conversation_state["estimated_cost"]}
🏪 Location: {self.conversation_state["nearest_store"]["name"]}
📍 Address: {self.conversation_state["nearest_store"]["address"]}
📱 IMEI: {self.conversation_state["imei"]}

Should I proceed with booking this appointment? Say 'yes' to confirm or 'no' to start over."""
        
        elif current_step == "confirmation":
            if any(word in user_input.lower() for word in ["yes", "confirm", "book", "schedule", "proceed"]):
                # Generate appointment details
                appointment = self.generate_appointment_details()
                self.conversation_state["step"] = "completed"
                
                device_name = self.conversation_state["device"].title()
                if self.conversation_state["device"] == "iphone":
                    device_name = "iPhone"
                elif self.conversation_state["device"] == "mac":
                    device_name = "Mac"
                
                response = f"""✅ Appointment Successfully Booked!

🎫 Confirmation Number: {appointment["confirmation"]}
📅 Date: {appointment["date"]}
🕐 Time: {appointment["time"]}
🏪 Store: {self.conversation_state["nearest_store"]["name"]}
📞 Store Phone: {self.conversation_state["nearest_store"]["phone"]}
📍 Address: {self.conversation_state["nearest_store"]["address"]}

📝 What to bring:
• Government-issued photo ID
• Your {device_name}
• Proof of purchase (if available)

⚠️ Before your appointment:
• Back up your device
• Turn off Find My iPhone (if applicable)
• Remove any cases or screen protectors

Your repair is scheduled! A confirmation has been sent to your Apple ID email. Is there anything else I can help you with today?"""
            elif any(word in user_input.lower() for word in ["no", "cancel", "start over"]):
                self.reset_conversation()
                response = "No problem! Let's start fresh. What device needs repair today?"
            else:
                response = "I need you to confirm the appointment. Please say 'yes' to proceed with booking or 'no' to start over."
        
        elif current_step == "completed":
            if any(word in user_input.lower() for word in ["thank", "thanks", "bye", "goodbye"]):
                response = "You're very welcome! Have a great day, and we'll see you at your appointment. If you need to reschedule or have questions, you can call the store directly or visit support.apple.com."
            elif any(word in user_input.lower() for word in ["new", "another", "different", "help"]):
                self.reset_conversation()
                response = "I'd be happy to help with another repair. What device needs assistance today?"
            else:
                response = "Your appointment is all set! Is there anything else I can help you with today, or would you like to schedule another repair?"
        
        # Add response to history
        self.conversation_state["history"].append({"role": "assistant", "content": response})
        
        return response

# Initialize the concierge
concierge = AppleCareVoiceConcierge()

def process_transcribed_text(transcribed_text):
    """Process transcribed text from speech input"""
    if not transcribed_text.strip():
        return "I didn't catch that. Please try speaking again.", concierge.conversation_state["history"]
    
    response = concierge.process_conversation(transcribed_text)
    
    # Format conversation history for display
    history = []
    for msg in concierge.conversation_state["history"][-10:]:
        role = "🗣️ You" if msg["role"] == "user" else "🤖 Concierge"
        history.append(f"{role}: {msg['content']}")
    
    return response, "\n\n".join(history)

def text_input_handler(text_input):
    """Handle text input for testing"""
    if not text_input.strip():
        return "Please enter a message.", concierge.conversation_state["history"]
    
    response = concierge.process_conversation(text_input)
    
    # Format conversation history for display
    history = []
    for msg in concierge.conversation_state["history"][-10:]:
        role = "🗣️ You" if msg["role"] == "user" else "🤖 Concierge"
        history.append(f"{role}: {msg['content']}")
    
    return response, "\n\n".join(history)

def reset_conversation():
    """Reset the conversation"""
    concierge.reset_conversation()
    return "Conversation reset! Hello! I'm your AppleCare concierge. How can I help with your device today?", ""

# Create Gradio interface with mystical orange and dark blue neomorphic design
def create_interface():
    with gr.Blocks(
        css="""
        .gradio-container {
            max-width: 900px !important;
            margin: 0 auto !important;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        .main-container {
            background: linear-gradient(145deg, #1a1f35, #0d1226);
            border-radius: 24px;
            box-shadow: 20px 20px 60px #0a0e1d, -20px -20px 60px #20284d;
            padding: 30px;
            margin: 20px auto;
            border: 1px solid #ff7b25;
        }
        .title {
            text-align: center;
            color: #ff7b25;
            margin-bottom: 25px;
            font-weight: 800;
            font-size: 32px;
            text-shadow: 0 0 10px rgba(255, 123, 37, 0.5);
        }
        .subtitle {
            text-align: center;
            color: #64b5f6;
            margin-bottom: 30px;
            font-size: 18px;
        }
        .response-box {
            background: linear-gradient(145deg, #1e243b, #151a30);
            border-radius: 20px;
            box-shadow: inset 5px 5px 10px #0d111f, inset -5px -5px 10px #272f57;
            padding: 20px;
            margin: 15px 0;
            border: none;
            min-height: 200px;
            color: #ff7b25;
            font-weight: 500;
        }
        .conversation-history {
            background: linear-gradient(145deg, #1e243b, #151a30);
            border-radius: 20px;
            box-shadow: inset 5px 5px 10px #0d111f, inset -5px -5px 10px #272f57;
            padding: 20px;
            margin: 15px 0;
            border: none;
            min-height: 300px;
            max-height: 400px;
            overflow-y: auto;
            color: #64b5f6;
        }
        .btn-primary {
            background: linear-gradient(145deg, #ff7b25, #e55a00);
            border: none;
            border-radius: 16px;
            box-shadow: 5px 5px 10px #0d111f, -5px -5px 10px #272f57;
            color: #0d1226;
            padding: 12px 25px;
            margin: 8px;
            transition: all 0.3s ease;
            font-weight: 600;
        }
        .btn-primary:hover {
            box-shadow: 3px 3px 6px #0d111f, -3px -3px 6px #272f57;
            transform: translateY(2px);
            background: linear-gradient(145deg, #e55a00, #ff7b25);
        }
        .btn-secondary {
            background: linear-gradient(145deg, #64b5f6, #2196f3);
            border: none;
            border-radius: 16px;
            box-shadow: 5px 5px 10px #0d111f, -5px -5px 10px #272f57;
            color: #0d1226;
            padding: 12px 25px;
            margin: 8px;
            transition: all 0.3s ease;
            font-weight: 600;
        }
        .btn-secondary:hover {
            box-shadow: 3px 3px 6px #0d111f, -3px -3px 6px #272f57;
            transform: translateY(2px);
            background: linear-gradient(145deg, #2196f3, #64b5f6);
        }
        .btn-stop {
            background: linear-gradient(145deg, #f44336, #d32f2f);
            border: none;
            border-radius: 16px;
            box-shadow: 5px 5px 10px #0d111f, -5px -5px 10px #272f57;
            color: white;
            padding: 12px 25px;
            margin: 8px;
            transition: all 0.3s ease;
            font-weight: 600;
        }
        .btn-stop:hover {
            box-shadow: 3px 3px 6px #0d111f, -3px -3px 6px #272f57;
            transform: translateY(2px);
            background: linear-gradient(145deg, #d32f2f, #f44336);
        }
        .audio-input {
            border-radius: 16px;
            background: linear-gradient(145deg, #1e243b, #151a30);
            box-shadow: inset 5px 5px 10px #0d111f, inset -5px -5px 10px #272f57;
            padding: 15px;
            margin: 10px 0;
            border: 1px solid #ff7b25;
        }
        .text-input {
            border-radius: 16px;
            background: linear-gradient(145deg, #1e243b, #151a30);
            box-shadow: inset 5px 5px 10px #0d111f, inset -5px -5px 10px #272f57;
            padding: 15px;
            margin: 10px 0;
            border: 1px solid #64b5f6;
            color: #64b5f6;
        }
        .label {
            font-weight: 600;
            color: #ff7b25;
            margin-bottom: 8px;
            display: block;
        }
        .footer {
            text-align: center;
            margin-top: 25px;
            color: #64b5f6;
            font-size: 14px;
        }
        .status-indicator {
            text-align: center;
            margin: 10px 0;
            color: #ff7b25;
            font-style: italic;
        }
        /* Scrollbar styling */
        .conversation-history::-webkit-scrollbar {
            width: 8px;
        }
        .conversation-history::-webkit-scrollbar-track {
            background: #151a30;
            border-radius: 4px;
        }
        .conversation-history::-webkit-scrollbar-thumb {
            background: #ff7b25;
            border-radius: 4px;
        }
        .conversation-history::-webkit-scrollbar-thumb:hover {
            background: #e55a00;
        }
        """
    ) as interface:
        
        # Add Transformers.js code
        gr.HTML(transformers_js_code)
        
        gr.HTML("""
        <div class="title">🍎 AppleCare Voice Concierge</div>
        <div class="subtitle">Your mystical AI-powered device repair assistant</div>
        """)
        
        with gr.Column(elem_classes="main-container"):
            # Status indicator
            gr.HTML("""
            <div class="status-indicator" id="status-text">
                Loading speech models...
            </div>
            """)
            
            # Voice input
            with gr.Row():
                audio_input = gr.Audio(
                    sources=["microphone"],
                    type="filepath",
                    label="🎤 Click to speak - I'm listening",
                    elem_classes="audio-input"
                )
            
            # Hidden transcript input for JavaScript to use
            hidden_transcript = gr.Textbox(visible=False, elem_id="hidden-transcript")
            
            # Text input for testing
            with gr.Row():
                text_input = gr.Textbox(
                    placeholder="Or type your message here...",
                    label="💬 Text Input",
                    lines=2,
                    elem_classes="text-input"
                )
            
            # Buttons
            with gr.Row():
                submit_text_btn = gr.Button("📝 Send Text", elem_classes="btn-secondary")
                reset_btn = gr.Button("🔄 Reset Conversation", elem_classes="btn-stop")
                speak_btn = gr.Button("🔊 Speak Response", elem_classes="btn-primary")
            
            # AI Response
            ai_response = gr.Textbox(
                label="🤖 Concierge Response",
                value="Hello! I'm your AppleCare concierge. How can I help with your device today?",
                lines=8,
                interactive=False,
                elem_classes="response-box",
                elem_id="ai-response"
            )
            
            # Conversation History
            conversation_history = gr.Textbox(
                label="📝 Conversation History",
                lines=10,
                interactive=False,
                elem_classes="conversation-history"
            )
        
        gr.HTML("""
        <div class="footer">
            <p>This AI concierge uses Transformers.js for speech processing - no API keys required</p>
            <p>✅ Check device issues • 📍 Find nearby Apple Stores • 📅 Schedule appointments • 💰 Get repair estimates</p>
        </div>
        """)
        
        # Event handlers
        hidden_transcript.change(
            fn=process_transcribed_text,
            inputs=[hidden_transcript],
            outputs=[ai_response, conversation_history]
        )
        
        submit_text_btn.click(
            fn=text_input_handler,
            inputs=[text_input],
            outputs=[ai_response, conversation_history]
        )
        
        text_input.submit(
            fn=text_input_handler,
            inputs=[text_input],
            outputs=[ai_response, conversation_history]
        )
        
        reset_btn.click(
            fn=reset_conversation,
            outputs=[ai_response, conversation_history]
        )
        
        # JavaScript for handling audio recording
        gr.HTML("""
        <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Get the audio input element
            const audioInput = document.querySelector('input[type="file"]');
            if (audioInput) {
                audioInput.addEventListener('change', function(event) {
                    const file = event.target.files[0];
                    if (file) {
                        // Handle the audio recording
                        handleAudioRecording(file);
                    }
                });
            }
            
            // Add event listener for the speak button
            const speakButton = document.querySelector('.btn-primary');
            if (speakButton) {
                speakButton.addEventListener('click', function() {
                    const responseText = document.querySelector('#ai-response textarea').value;
                    if (responseText) {
                        speakText(responseText);
                    }
                });
            }
        });
        </script>
        """)
    
    return interface

# Launch the app
if __name__ == "__main__":
    interface = create_interface()
    interface.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False
    )