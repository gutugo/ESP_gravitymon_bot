import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from contextlib import asynccontextmanager

from config import settings
import database
import alerts


class ISpindelPayload(BaseModel):
    """iSpindel/GravityMon HTTP POST format."""
    name: str
    ID: str
    token: Optional[str] = ""
    interval: Optional[int] = 900
    temperature: float
    temp_units: Optional[str] = "C"
    gravity: float
    angle: Optional[float] = None
    battery: float
    RSSI: Optional[int] = None
    corr_gravity: Optional[float] = None
    gravity_unit: Optional[str] = "G"
    run_time: Optional[int] = None

    class Config:
        populate_by_name = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    await database.init_db()
    print("Database initialized")
    yield


app = FastAPI(
    title="GravityMon API",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "gravitymon-api"}


@app.post("/api/v1/webhook")
async def receive_data(
    payload: ISpindelPayload,
    authorization: Optional[str] = Header(None)
):
    """
    Receive and store data from GravityMon/iSpindel device.

    Expected JSON format:
    {
        "name": "device_name",
        "ID": "device_id",
        "temperature": 20.5,
        "temp_units": "C",
        "gravity": 1.052,
        "battery": 3.89,
        "RSSI": -65,
        "interval": 900
    }
    """
    # Optional token verification
    if settings.api_token:
        expected = f"Bearer {settings.api_token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # Register/update device
        await database.upsert_device(
            device_id=payload.ID,
            name=payload.name
        )

        # Store reading
        await database.insert_reading(
            device_id=payload.ID,
            temperature=payload.temperature,
            temp_unit=payload.temp_units or "C",
            gravity=payload.gravity,
            gravity_unit=payload.gravity_unit or "G",
            battery=payload.battery,
            angle=payload.angle,
            rssi=payload.RSSI,
            interval_sec=payload.interval
        )

        print(f"Received data from {payload.name}: temp={payload.temperature}, gravity={payload.gravity}, battery={payload.battery}")

        # Check and send alerts (async, don't wait)
        asyncio.create_task(
            alerts.check_and_send_alerts(
                device_id=payload.ID,
                device_name=payload.name,
                battery=payload.battery
            )
        )

        return {
            "status": "ok",
            "device": payload.name,
            "device_id": payload.ID
        }

    except Exception as e:
        print(f"Error processing data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/devices")
async def list_devices():
    """List all registered devices."""
    devices = await database.get_all_devices()
    return {"devices": devices}


@app.get("/api/v1/devices/{device_id}/status")
async def get_device_status(device_id: str):
    """Get latest reading for a device."""
    reading = await database.get_latest_reading(device_id)
    if not reading:
        raise HTTPException(status_code=404, detail="Device not found or no readings")
    return reading


@app.get("/api/v1/devices/{device_id}/readings")
async def get_device_readings(
    device_id: str,
    period: str = "day"
):
    """Get readings for a specific period."""
    if period not in ['hour', 'day', 'week', 'month']:
        raise HTTPException(status_code=400, detail="Invalid period")

    readings = await database.get_readings_for_period(device_id, period)
    return {"readings": readings, "count": len(readings)}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False
    )
