import pytest
from unittest.mock import MagicMock, patch
from core.pipeline import Pipeline

# A simplified setup for the Pipeline, as we only need to test one method.
def create_pipeline(config):
    # We pass mocks for dependencies that are not used in the method under test.
    return Pipeline(
        config=config,
        db=MagicMock(),
        collector=MagicMock(),
        tester=MagicMock(),
        uploader=MagicMock(),
        stats=MagicMock(),
        shutdown_event=MagicMock()
    )

@patch('core.pipeline.shutil.rmtree')
@patch('core.pipeline.Path')
def test_cleanup_deletes_dir_when_enabled(mock_path, mock_rmtree):
    """Verify that the cleanup function DELETES the directory when the config is true."""
    # Arrange: Mock the path to exist
    mock_home_dir = MagicMock()
    mock_knife_dir = mock_home_dir / ".xray-knife"
    mock_knife_dir.exists.return_value = True
    mock_path.home.return_value = mock_home_dir

    config = {'logging': {'cleanup_xray_knife_dir': True}}
    pipeline = create_pipeline(config)

    # Act
    pipeline._cleanup_xray_knife_db()

    # Assert
    mock_path.home.assert_called_once()
    mock_rmtree.assert_called_once_with(mock_knife_dir)

@patch('core.pipeline.shutil.rmtree')
@patch('core.pipeline.Path')
def test_cleanup_does_not_delete_when_disabled(mock_path, mock_rmtree):
    """Verify that the cleanup function DOES NOT delete the directory when the config is false."""
    # Arrange
    config = {'logging': {'cleanup_xray_knife_dir': False}}
    pipeline = create_pipeline(config)

    # Act
    pipeline._cleanup_xray_knife_db()

    # Assert
    # The function should return early, so no calls to Path or rmtree should be made.
    mock_path.home.assert_not_called()
    mock_rmtree.assert_not_called()

@patch('core.pipeline.shutil.rmtree')
@patch('core.pipeline.Path')
def test_cleanup_does_not_delete_when_missing(mock_path, mock_rmtree):
    """Verify that the cleanup function DOES NOT delete the directory when the config is missing."""
    # Arrange
    config = {'logging': {}} # cleanup_xray_knife_dir is missing
    pipeline = create_pipeline(config)

    # Act
    pipeline._cleanup_xray_knife_db()

    # Assert
    # The function should return early, so no calls to Path or rmtree should be made.
    mock_path.home.assert_not_called()
    mock_rmtree.assert_not_called()

@patch('core.pipeline.shutil.rmtree')
@patch('core.pipeline.Path')
def test_cleanup_does_nothing_if_dir_not_exists(mock_path, mock_rmtree):
    """Verify that shutil.rmtree is not called if the directory does not exist, even if enabled."""
    # Arrange: Mock the path to NOT exist
    mock_home_dir = MagicMock()
    mock_knife_dir = mock_home_dir / ".xray-knife"
    mock_knife_dir.exists.return_value = False
    mock_path.home.return_value = mock_home_dir

    config = {'logging': {'cleanup_xray_knife_dir': True}}
    pipeline = create_pipeline(config)

    # Act
    pipeline._cleanup_xray_knife_db()

    # Assert
    mock_path.home.assert_called_once()
    mock_rmtree.assert_not_called()
