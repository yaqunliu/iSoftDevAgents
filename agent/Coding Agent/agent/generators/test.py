from mock_runtime import simple_mock_validate

file_path = "/Users/lxx/Desktop/CodeAgent/my_soft_test_backend_compiled_20251128/backend/app/domain/AccountManagement/dto.py"
# after writing file
mock_result = simple_mock_validate(file_path)

if not mock_result.ok:
    print("❌ MOCK FAILED for", file_path)
    print(mock_result.errors)
    raise RuntimeError("Mock validation failed")
else:
    print("✔ MOCK PASSED for", file_path)