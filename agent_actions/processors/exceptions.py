"""
Processor-specific exception hierarchy.

This module defines custom exception classes for processor operations,
providing a consistent error handling structure across all processors.
"""


class ProcessorError(Exception):
    """Base exception class for all processor-related errors."""
    pass


# Loader-related exceptions
class LoaderError(ProcessorError):
    """Base exception for loader operations."""
    pass


class FileLoadError(LoaderError):
    """Raised when a file cannot be loaded."""
    pass


class DataParseError(LoaderError):
    """Raised when data cannot be parsed correctly."""
    pass


class UnsupportedFormatError(LoaderError):
    """Raised when an unsupported file format is encountered."""
    pass


# Processing-related exceptions
class ProcessingError(ProcessorError):
    """Base exception for processing operations."""
    pass


class ValidationError(ProcessingError):
    """Raised when data validation fails."""
    pass


class TransformationError(ProcessingError):
    """Raised when data transformation fails."""
    pass


class GenerationError(ProcessingError):
    """Raised when data generation fails."""
    pass


# Output-related exceptions
class OutputError(ProcessorError):
    """Base exception for output operations."""
    pass


class FileWriteError(OutputError):
    """Raised when a file cannot be written."""
    pass


class SerializationError(OutputError):
    """Raised when data cannot be serialized."""
    pass