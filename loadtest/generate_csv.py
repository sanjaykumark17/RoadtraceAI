import random
from datetime import datetime, timezone, timedelta

def generate_csv():
    base_time = datetime(2026, 10, 13, 8, 0, 0, tzinfo=timezone.utc)
    states = ["TN", "MH", "KA", "DL", "AP", "TS", "KL", "GJ"]
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"

    rows = ["plate_number,camera_id,latitude,longitude,timestamp"]
    for i in range(1500):
        cam_id = (i % 500) + 1
        state = random.choice(states)
        dist_code = f"{random.randint(1, 99):02d}"
        series = f"{random.choice(letters)}{random.choice(letters)}"
        num = f"{random.randint(1000, 9999)}"
        plate = f"{state}{dist_code}{series}{num}"

        # Coordinates along Chennai urban / arterial corridor (GST & ORR)
        lat = round(12.8797 + random.random() * (13.1147 - 12.8797), 5)
        lon = round(80.0652 + random.random() * (80.2475 - 80.0652), 5)

        ts = (base_time + timedelta(seconds=i * 2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(f"{plate},{cam_id},{lat},{lon},{ts}")

    with open("loadtest/cameras_sightings.csv", "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")

    print(f"Generated loadtest/cameras_sightings.csv with {len(rows) - 1} records across 500 virtual cameras.")

if __name__ == "__main__":
    generate_csv()
