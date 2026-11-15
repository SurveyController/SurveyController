from qfluentwidgets import IndeterminateProgressBar as FluentIndeterminateProgressBar


class IndeterminateProgressBar(FluentIndeterminateProgressBar):
    def resume(self):
        if self.isError():
            return
        if self.isPaused():
            super().resume()
        elif not self.isStarted():
            self.start()

    def setPaused(self, isPaused):
        if isPaused:
            if self.isStarted():
                self.pause()
        else:
            self.resume()
