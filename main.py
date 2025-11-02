import os
import json
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from schemas import Appointment
from database import create_document

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}

@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    
    try:
        # Try to import database module
        from database import db
        
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            
            # Try to list collections to verify connectivity
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]  # Show first 10 collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
            
    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    
    # Check environment variables
    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    
    return response

# Optional integrations

def _append_to_google_sheets(appointment: Appointment) -> Optional[str]:
    """Append appointment data to a Google Sheet if credentials are present.
    Returns worksheet title on success, None otherwise.
    """
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    spreadsheet_name = os.getenv("GOOGLE_SHEETS_SPREADSHEET")
    worksheet_name = os.getenv("GOOGLE_SHEETS_WORKSHEET", "Sheet1")

    if not service_account_json or not spreadsheet_name:
        return None

    try:
        import gspread
        from google.oauth2.service_account import Credentials
        data = json.loads(service_account_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(data, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open(spreadsheet_name)
        try:
            ws = sh.worksheet(worksheet_name)
        except Exception:
            ws = sh.sheet1
        ws.append_row([
            appointment.name,
            appointment.email,
            appointment.phone,
            appointment.department,
            appointment.date or "",
            appointment.notes or ""
        ])
        return ws.title
    except Exception as e:
        # Swallow errors to not break the API flow
        print(f"Google Sheets integration error: {e}")
        return None


def _send_whatsapp_notification(appointment: Appointment) -> Optional[str]:
    """Send a WhatsApp notification via Twilio if credentials are present.
    Returns message SID on success, None otherwise.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_whatsapp = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g., 'whatsapp:+14155238886'
    to_whatsapp = os.getenv("WHATSAPP_TO")             # e.g., 'whatsapp:+15551234567'

    if not all([account_sid, auth_token, from_whatsapp, to_whatsapp]):
        return None

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        body = (
            f"New Appointment Request\n"
            f"Name: {appointment.name}\n"
            f"Email: {appointment.email}\n"
            f"Phone: {appointment.phone}\n"
            f"Department: {appointment.department}\n"
            f"Date: {appointment.date or '-'}\n"
            f"Notes: {appointment.notes or '-'}"
        )
        msg = client.messages.create(body=body, from_=from_whatsapp, to=to_whatsapp)
        return msg.sid
    except Exception as e:
        print(f"WhatsApp integration error: {e}")
        return None


@app.post("/appointments")
def create_appointment(appointment: Appointment):
    """Create an appointment, persist to DB, and trigger optional integrations."""
    try:
        inserted_id = create_document("appointment", appointment)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    sheet_ws = _append_to_google_sheets(appointment)
    whatsapp_sid = _send_whatsapp_notification(appointment)

    return {
        "ok": True,
        "id": inserted_id,
        "google_sheets": bool(sheet_ws),
        "whatsapp": bool(whatsapp_sid)
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
