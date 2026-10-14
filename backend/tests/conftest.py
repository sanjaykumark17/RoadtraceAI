import os

os.environ.setdefault("RT_ADMIN_PASSWORD", "test-admin-pass-987")
os.environ.setdefault("RT_OPERATOR_PASSWORD", "test-operator-pass-654")
os.environ.setdefault("RT_VIEWER_PASSWORD", "test-viewer-pass-321")

TEST_ADMIN_PASSWORD = os.environ["RT_ADMIN_PASSWORD"]
TEST_OPERATOR_PASSWORD = os.environ["RT_OPERATOR_PASSWORD"]
TEST_VIEWER_PASSWORD = os.environ["RT_VIEWER_PASSWORD"]
