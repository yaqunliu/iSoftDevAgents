
"""
测试模块描述:
用于测试处理命令行接口的功能模块
"""
import pytest
from unittest.mock import patch, MagicMock

# 假设Global_functions在my_module模块中
from my_module import Global_functions

@pytest.fixture
def mock_open():
    """Fixture to mock open function for file operations"""
    with patch("builtins.open", MagicMock()) as mock:
        yield mock

class TestGlobalFunctions:
    """测试 Global_functions 类"""

    def test_parse_csv_file_when_filepath_is_valid_should_return_parsed_data(self, mock_open):
        """测试 parse_csv_file 方法当文件路径有效时应返回解析后的数据"""
        # Arrange
        valid_csv_filepath = "valid/path/to/file.csv"
        expected_data = {"key": "value"}  # 假设解析后返回的数据格式
        mock_open().read.return_value = 'CSV header\nvalue'

        # Act
        result = Global_functions.parse_csv_file(valid_csv_filepath)

        # Assert
        assert result == expected_data

    def test_parse_csv_file_when_filepath_is_invalid_should_raise_exception(self):
        """测试 parse_csv_file 方法当文件路径无效时应抛出异常"""
        # Arrange
        invalid_csv_filepath = "invalid/path/to/file.csv"

        # Act & Assert
        with pytest.raises(FileNotFoundError):
            Global_functions.parse_csv_file(invalid_csv_filepath)

    def test_parse_json_file_when_filepath_is_valid_should_return_parsed_data(self, mock_open):
        """测试 parse_json_file 方法当文件路径有效时应返回解析后的数据"""
        # Arrange
        valid_json_filepath = "valid/path/to/file.json"
        expected_data = {"key": "value"}  # 假设解析后返回的数据格式
        mock_open().read.return_value = '{"key": "value"}'

        # Act
        result = Global_functions.parse_json_file(valid_json_filepath)

        # Assert
        assert result == expected_data

    def test_parse_json_file_when_filepath_is_invalid_should_raise_exception(self):
        """测试 parse_json_file 方法当文件路径无效时应抛出异常"""
        # Arrange
        invalid_json_filepath = "invalid/path/to/file.json"

        # Act & Assert
        with pytest.raises(FileNotFoundError):
            Global_functions.parse_json_file(invalid_json_filepath)

    def test_output_json_when_structure_and_filepath_are_valid_should_write_to_file(self, mock_open):
        """测试 output_json 方法当 json 结构和文件路径有效时应写入文件"""
        # Arrange
        json_struct = {"key": "value"}
        json_filepath = "valid/path/to/output.json"

        # Act
        Global_functions.output_json(json_struct, json_filepath)

        # Assert
        mock_open.assert_called_once_with(json_filepath, 'w')
        handle = mock_open().__enter__()
        handle.write.assert_called_once_with('{\n    "key": "value"\n}')

    def test_output_json_when_structure_is_invalid_should_raise_exception(self, mock_open):
        """测试 output_json 方法当 json 结构无效时应抛出异常"""
        # Arrange
        invalid_json_struct = None
        json_filepath = "valid/path/to/output.json"

        # Act & Assert
        with pytest.raises(TypeError):
            Global_functions.output_json(invalid_json_struct, json_filepath)
