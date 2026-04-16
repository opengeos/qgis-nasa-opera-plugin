"""
Worker Thread for NASA OPERA AI Agent.

Provides a QThread-based worker that runs the agent loop in the background
while communicating with the main thread via signals for tool execution
and streaming text updates.
"""

import json

from qgis.PyQt.QtCore import QThread, QMutex, QWaitCondition, pyqtSignal

from .agent import OperaAgent


class AgentWorker(QThread):
    """Worker thread that runs the AI agent loop.

    Tool execution that requires QGIS API access is dispatched to the main
    thread via the execute_tool_request signal. The main thread calls
    provide_tool_result() to unblock this worker.
    """

    text_chunk = pyqtSignal(str)
    tool_call_started = pyqtSignal(str, str)  # tool_name, json_args
    tool_call_result = pyqtSignal(str, str)  # tool_name, json_result
    finished = pyqtSignal(str)  # full response text
    error = pyqtSignal(str)
    execute_tool_request = pyqtSignal(str, str)  # tool_name, json_args

    def __init__(self, agent: OperaAgent, message: str):
        """Initialize the worker.

        Args:
            agent: The OperaAgent instance.
            message: User message to process.
        """
        super().__init__()
        self.agent = agent
        self.message = message
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._tool_result = None
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the agent loop."""
        self._cancelled = True

    def provide_tool_result(self, result: dict):
        """Provide a tool execution result from the main thread.

        This unblocks the worker thread which is waiting in
        _execute_tool_on_main_thread().

        Args:
            result: The tool execution result dict.
        """
        self._mutex.lock()
        self._tool_result = result
        self._condition.wakeOne()
        self._mutex.unlock()

    def _execute_tool_on_main_thread(self, name: str, args: dict) -> dict:
        """Request tool execution on the main thread and wait for result.

        Args:
            name: Tool name.
            args: Tool arguments.

        Returns:
            Tool execution result dict.
        """
        if self._cancelled:
            return {"error": "Operation cancelled by user."}

        self._mutex.lock()
        self._tool_result = None
        self.execute_tool_request.emit(name, json.dumps(args))
        # Wait up to 60 seconds for tool execution on main thread
        if not self._condition.wait(self._mutex, 60000):
            self._mutex.unlock()
            return {"error": "Tool execution timed out (60s)."}
        result = self._tool_result
        self._mutex.unlock()

        return result if result is not None else {"error": "No result received."}

    def run(self):
        """Execute the agent loop in the background thread."""
        try:
            if self._cancelled:
                return

            def on_text_chunk(chunk):
                if not self._cancelled:
                    self.text_chunk.emit(chunk)

            def on_tool_call(tool_name, args):
                if not self._cancelled:
                    self.tool_call_started.emit(tool_name, json.dumps(args))

            def on_tool_result(tool_name, result):
                if not self._cancelled:
                    self.tool_call_result.emit(tool_name, json.dumps(result))

            response = self.agent.process_message(
                self.message,
                on_text_chunk=on_text_chunk,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
                execute_tool_fn=self._execute_tool_on_main_thread,
            )

            if not self._cancelled:
                self.finished.emit(response)

        except Exception as e:
            if not self._cancelled:
                self.error.emit(str(e))
