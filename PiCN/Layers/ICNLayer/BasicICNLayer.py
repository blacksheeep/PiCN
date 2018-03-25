"""Basic ICN Forwarding Layer"""

import multiprocessing
import threading
import time
from typing import List

from PiCN.Layers.ICNLayer.ContentStore import BaseContentStore
from PiCN.Layers.ICNLayer.ForwardingInformationBase import BaseForwardingInformationBase, ForwardingInformationBaseEntry

from PiCN.Layers.ICNLayer.PendingInterestTable import BasePendingInterestTable, PendingInterestTableEntry
from PiCN.Packets import Name, Content, Interest, Packet, Nack, NackReason
from PiCN.Processes import LayerProcess


class BasicICNLayer(LayerProcess):
    """ICN Forwarding Plane. Maintains data structures for ICN Forwarding"""

    def __init__(self, cs: BaseContentStore=None, pit: BasePendingInterestTable=None,
                 fib: BaseForwardingInformationBase=None, log_level=255):
        super().__init__(logger_name="ICNLayer", log_level=log_level)
        self._cs: BaseContentStore = cs
        self._pit: BasePendingInterestTable = pit
        self._fib: BaseContentStore = fib
        self._cs_timeout: int = 10
        self._pit_timeout: int = 10
        self._pit_retransmits: int = 3
        self._ageing_interval: int = 4
        self._interest_to_app: bool = False

    def data_from_higher(self, to_lower: multiprocessing.Queue, to_higher: multiprocessing.Queue, data):
        high_level_id = data[0]
        packet = data[1]
        if isinstance(packet, Interest):
            cs_entry = self._cs.find_content_object(packet.name)
            if cs_entry is not None:
                self.queue_to_higher.put([high_level_id, cs_entry.content])
                return
            pit_entry = self._pit.find_pit_entry(packet.name)
            self._pit.add_pit_entry(packet.name, high_level_id, packet, local_app=True)
            fib_entry = self._fib.find_fib_entry(packet.name)
            if fib_entry is not None:
                self._pit.add_used_fib_entry(packet.name, fib_entry)
                to_lower.put([fib_entry.faceid, packet])
            else:
                self.logger.info("No FIB entry, sending Nack")
                nack = Nack(packet.name, NackReason.NO_ROUTE, interest=packet)
                if pit_entry is not None: #if pit entry is available, consider it, otherwise assume interest came from higher
                    for i in range(0, len(pit_entry.faceids)):
                        if pit_entry._local_app[i]:
                            to_higher.put([high_level_id, nack])
                        else:
                            to_lower.put([pit_entry._faceids[i], nack])
                else:
                    to_higher.put([high_level_id, nack])
        elif isinstance(packet, Content):
            self.handle_content(high_level_id, packet, to_lower, to_higher, True) #content handled same as for content from network
        elif isinstance(packet, Nack):
            self.handle_nack(high_level_id, packet, to_lower, to_higher, True) #Nack handled same as for NACK from network

    def data_from_lower(self, to_lower: multiprocessing.Queue, to_higher: multiprocessing.Queue, data):
        if len(data) != 2:
            self.logger.warning("ICN Layer expects to receive [face id, packet] from lower layer")
            return
        if type(data[0]) != int:
            self.logger.warning("ICN Layer expects to receive [face id, packet] from lower layer")
            return
        if not isinstance(data[1], Packet):
            self.logger.warning("ICN Layer expects to receive [face id, packet] from lower layer")
            return

        face_id = data[0]
        packet = data[1]
        if isinstance(packet, Interest):
            self.handle_interest(face_id, packet, to_lower, to_higher, False)
        elif isinstance(packet, Content):
            self.handle_content(face_id, packet, to_lower, to_higher, False)
        elif isinstance(packet, Nack):
            self.handle_nack(face_id, packet, to_lower, to_higher, False)

    def handle_interest(self, face_id: int, interest: Interest, to_lower: multiprocessing.Queue,
                        to_higher: multiprocessing.Queue, from_local: bool = False):
        self.logger.info("Handling Interest")
        #if to_higher is not None: #TODO check if app layer accepted the data, and change handling

        cs_entry = self.check_cs(interest)
        if cs_entry is not None:
            self.logger.info("Found in content store")
            to_lower.put([face_id, cs_entry.content])
            self._cs.update_timestamp(cs_entry)
            return
        pit_entry = self.check_pit(interest.name)
        if pit_entry is not None:
            self.logger.info("Found in PIT, appending")
            self._pit.update_timestamp(pit_entry)
            self._pit.add_pit_entry(interest.name, face_id, interest, local_app=from_local)
            return
        if self._interest_to_app is True and to_higher is not None: #App layer support
            self.logger.info("Sending to higher Layer")
            self._pit.add_pit_entry(interest.name, face_id, interest, local_app=from_local)
            self.queue_to_higher.put([face_id, interest])
            return
        new_face_id = self.check_fib(interest.name, None)
        if new_face_id is not None:
            self.logger.info("Found in FIB, forwarding")
            self._pit.add_pit_entry(interest.name, face_id, interest, local_app=from_local)
            self._pit.add_used_fib_entry(interest.name, new_face_id)
            to_lower.put([new_face_id.faceid, interest])
            return
        self.logger.info("No FIB entry, sending Nack")
        nack = Nack(interest.name, NackReason.NO_ROUTE, interest=interest)
        if from_local:
            to_higher.put([face_id, nack])
        else:
            to_lower.put([face_id, nack])

    def handle_content(self, face_id: int, content: Content, to_lower: multiprocessing.Queue,
                       to_higher: multiprocessing.Queue, from_local: bool = False):
        self.logger.info("Handling Content " + str(content.name) + " " + str(content.content))
        pit_entry = self.check_pit(content.name)
        if pit_entry is None:
            self.logger.info("No PIT entry for content object available, dropping")
            #todo NACK??
            return
        else:
            for i in range(0, len(pit_entry.faceids)):
                if to_higher and pit_entry.local_app[i]:
                    to_higher.put([face_id, content])
                else:
                    to_lower.put([pit_entry.faceids[i], content])
            self._pit.remove_pit_entry(pit_entry.name)
            self._cs.add_content_object(content)

    def handle_nack(self, face_id: int, nack: Nack, to_lower: multiprocessing.Queue,
                    to_higher: multiprocessing.Queue, from_local: bool = False):
        self.logger.info("Handling NACK")
        pit_entry = self.check_pit(nack.name)
        if pit_entry is None:
            self.logger.info("No PIT entry for NACK available, dropping")
            return
        else:
            fib_entry = self.check_fib(nack.name, pit_entry.fib_entries_already_used)
            if fib_entry is None:
                self.logger.info("Sending NACK to previous node(s)")
                re_add = False
                for i in range(0, len(pit_entry.faceids)):
                    if pit_entry.local_app[i] == True: #Go with NACK first only to app layer if it was requested
                        re_add = True
                self._pit.remove_pit_entry(pit_entry.name)
                for i in range(0, len(pit_entry.faceids)):
                    if to_higher and pit_entry.local_app[i]:
                        to_higher.put([face_id, nack])
                        del pit_entry.face_id[i]
                        del pit_entry.local_app[i]
                    elif not re_add:
                        to_lower.put([pit_entry.faceids[i], nack])
                if re_add:
                    self._pit.container.append(pit_entry)
            else:
                self.logger.info("Try using next FIB path")
                self._pit.add_used_fib_entry(nack.name, fib_entry)
                to_lower.put([fib_entry.faceid, pit_entry.interest])


    def ageing(self):
        """Ageing the data structs"""
        try:
            self.logger.debug("Ageing")
            self.pit_ageing()
            self.cs_ageing()
            t = threading.Timer(self._ageing_interval, self.ageing)
            t.setDaemon(True)
            t.start()
        except:
            pass

    def pit_ageing(self):
        """Ageing the PIT"""
        cur_time = time.time()
        remove = []
        updated = []
        for pit_entry in self._pit.container:
            if pit_entry.timestamp + self._pit_timeout < cur_time and pit_entry.retransmits > self._pit_retransmits:
                remove.append(pit_entry)
            else:
                pit_entry.retransmits = pit_entry.retransmits + 1
                updated.append(pit_entry)
                new_face_id = self.check_fib(pit_entry.name, pit_entry.fib_entries_already_used)
                if new_face_id is not None:
                    self.queue_to_lower.put([new_face_id.faceid, pit_entry.interest])
        for pit_entry in remove:
            self._pit.remove_pit_entry(pit_entry.name)
        for pit_entry in updated:
            self._pit.remove_pit_entry(pit_entry.name)
            self._pit.container.append(pit_entry)

    def cs_ageing(self):
        """Aging the CS"""
        cur_time = time.time()
        remove = []
        for cs_entry in self._cs.container:
            if cs_entry.static is True:
                continue
            if cs_entry.timestamp + self._cs_timeout < cur_time:
                remove.append(cs_entry)
        for cs_entry in remove:
            self._cs.remove_content_object(cs_entry.content.name)


    def check_cs(self, interest: Interest) -> Content:
        return self._cs.find_content_object(interest.name)

    def check_pit(self, name: Name) -> PendingInterestTableEntry:
        return self._pit.find_pit_entry(name)

    def check_fib(self, name: Name, already_used: List[ForwardingInformationBaseEntry]) -> ForwardingInformationBaseEntry:
        return self._fib.find_fib_entry(name, already_used=already_used)

    @property
    def cs(self):
        """The Content Store"""
        return self._cs

    @cs.setter
    def cs(self, cs):
        self._cs = cs

    @property
    def fib(self):
        """The Forwarding Information Base"""
        return self._fib

    @fib.setter
    def fib(self, fib):
        self._fib = fib

    @property
    def pit(self):
        """The Pending Interest Table"""
        return self._pit

    @pit.setter
    def pit(self, pit):
        self._pit = pit
