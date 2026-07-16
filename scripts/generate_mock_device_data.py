import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models import Device, DeviceAlarmRecord, DeviceRuntimeData  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate mock device data.")
    parser.add_argument("--device-code", default="DEV-001")
    parser.add_argument("--name", default="Demo Device")
    parser.add_argument("--device-type", default="pump")
    parser.add_argument("--location", default="Workshop A")
    parser.add_argument("--runtime-count", type=int, default=20)
    parser.add_argument("--alarm-count", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        device = (
            db.query(Device)
            .filter(Device.device_code == args.device_code)
            .one_or_none()
        )
        if device is None:
            device = Device(
                device_code=args.device_code,
                name=args.name,
                device_type=args.device_type,
                location=args.location,
                is_online=True,
            )
            db.add(device)
            db.commit()
            db.refresh(device)

        now = datetime.utcnow()
        statuses = ["normal", "normal", "normal", "warning"]
        for index in range(args.runtime_count):
            recorded_at = now - timedelta(minutes=args.runtime_count - index)
            db.add(
                DeviceRuntimeData(
                    device_id=device.id,
                    temperature=round(random.uniform(35.0, 88.0), 2),
                    voltage=round(random.uniform(210.0, 235.0), 2),
                    current=round(random.uniform(4.0, 12.0), 2),
                    vibration=round(random.uniform(0.1, 3.8), 2),
                    status=random.choice(statuses),
                    recorded_at=recorded_at,
                )
            )

        alarm_codes = ["E101", "E203", "W301", "E404"]
        alarm_levels = ["low", "medium", "high"]
        for index in range(args.alarm_count):
            occurred_at = now - timedelta(minutes=(index + 1) * 7)
            db.add(
                DeviceAlarmRecord(
                    device_id=device.id,
                    alarm_code=random.choice(alarm_codes),
                    alarm_level=random.choice(alarm_levels),
                    message="Mock alarm generated for milestone 2 demo.",
                    is_resolved=False,
                    occurred_at=occurred_at,
                )
            )

        db.commit()
        print(
            "Generated "
            f"{args.runtime_count} runtime rows and {args.alarm_count} alarms "
            f"for {args.device_code}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
