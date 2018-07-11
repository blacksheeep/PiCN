import multiprocessing
from math import pow

from PiCN.Processes import LayerProcess
from PiCN.Packets import Name, Interest, Content, Nack, NackReason


class PinnedComputationLayer(LayerProcess):
    def __init__(self, replica_id, log_level=255):
        super().__init__(logger_name="PinnedNFNLayer (" + str(replica_id) + ")", log_level=log_level)
        self.storage = None

    def data_from_higher(self, to_lower: multiprocessing.Queue, to_higher: multiprocessing.Queue, data):
        pass  # this is already the highest layer.

    def data_from_lower(self, to_lower: multiprocessing.Queue, to_higher: multiprocessing.Queue, data):
        self.logger.info("Received packet")
        packet_id = data[0]
        packet = data[1]
        if isinstance(packet, Interest):
            self.logger.info("Received packet is an interest")
            self.handleInterest(packet_id, packet)
        else:
            self.logger.info("Received packet is not an interest")
            return

    def return_result(self, packet_id, content: Content):
        self.queue_to_lower.put([packet_id, content])

    def return_nack(self, packet_id, interest: Interest):
        self.queue_to_lower.put([packet_id, Nack(interest.name, reason=NackReason.NOT_SET, interest=interest)])  # TODO -- choose an appropriate NACK reason

    def handleInterest(self, packet_id: int, interest: Interest):
        components = interest.name.components
        if components[-1] == b"pNFN":
            try:
                num_params = int(components[-2])
                params = components[-num_params - 2:-2]
                params = list(map(lambda x: x.decode('utf-8'), params))
                assert(num_params < len(interest.name.components)-2)
                function_name = components[:-num_params - 2]
                function_name = "/" + "/".join(list(map(lambda x: x.decode('utf-8'), function_name)))
            except:
                self.return_nack(packet_id, interest)
                self.logger.info("Invalid computation expression. Return NACK.")
                return
            if function_name == "/the/prefix/square":
                result = self.pinned_function_square(params)
                self.return_result(packet_id, Content(interest.name, str(result)))  # QUESTION -- return as string?
                self.logger.info("Result returned")
                return
            else:
                self.return_nack(packet_id, interest)
                self.logger.info("Pinned function not available. Return NACK.")
                return

        else:
            self.logger.info("Received interest does not contain a computation expression")
        return

    def pinned_function_square(self, params):
        # TODO -- check if params contains valid parameters
        return int(pow(int(params[0]), 2))

    def ageing(self):
        pass  # ageing not necessary