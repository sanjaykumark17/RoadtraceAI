import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class CameraStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    maintenance = "maintenance"


class VehicleClass(str, enum.Enum):
    passenger_car = "passenger_car"
    commercial_truck = "commercial_truck"
    public_bus = "public_bus"
    two_wheeler = "two_wheeler"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
