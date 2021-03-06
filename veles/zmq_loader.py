# -*- coding: utf-8 -*-
"""
.. invisible:
     _   _ _____ _     _____ _____
    | | | |  ___| |   |  ___/  ___|
    | | | | |__ | |   | |__ \ `--.
    | | | |  __|| |   |  __| `--. \
    \ \_/ / |___| |___| |___/\__/ /
     \___/\____/\_____|____/\____/

Created on Apr 2, 2014

███████████████████████████████████████████████████████████████████████████████

Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.

███████████████████████████████████████████████████████████████████████████████
"""


import six
import zmq
from zope.interface import implementer

from six.moves import queue
from veles.txzmq import ZmqConnection, ZmqEndpoint
from veles.distributable import IDistributable
from veles.loader.base import UserLoaderRegistry
from veles.units import Unit, IUnit


class ZmqRouter(ZmqConnection):
    socketType = zmq.ROUTER

    def __init__(self, owner, *endpoints):
        super(ZmqRouter, self).__init__(endpoints)
        self._owner = owner
        self.routing = {}

    @property
    def owner(self):
        return self._owner

    @owner.setter
    def owner(self, value):
        self._owner = value

    def messageReceived(self, message):
        routing, cid, payload = message
        self.routing[cid] = routing
        self.owner.receive_data(cid, payload)

    def reply(self, cid, message):
        self.send(self.routing.pop(cid), cid, message)


@six.add_metaclass(UserLoaderRegistry)
@implementer(IUnit, IDistributable)
class ZeroMQLoader(Unit):
    """
    Listens to incoming ZeroMQ sockets.
    """

    def __init__(self, workflow, **kwargs):
        super(ZeroMQLoader, self).__init__(workflow, **kwargs)
        self._queue = queue.Queue(kwargs.get("queue_size", 0))
        self.output = 0
        self.cid = None
        self._endpoints = {}
        self.negotiates_on_connect = True

    @property
    def endpoints(self):
        return self._endpoints

    def initialize(self, **kwargs):
        if not self.is_slave:
            return
        self.endpoints.update({
            "inproc":
            ZmqEndpoint("bind", "inproc://veles-zmqloader-%s" % self.name),
            "ipc":
            ZmqEndpoint("bind", "rndipc://veles-ipc-zmqloader-:"),
            "tcp":
            ZmqEndpoint("bind", "rndtcp://*:1024:65535:1")})
        self._zmq_socket = ZmqRouter(self, *sorted(self.endpoints.values()))

        zmq_ipc_fn, zmq_tcp_port = self._zmq_socket.rnd_vals
        self.endpoints.update({
            "inproc":
            ZmqEndpoint("connect", self.endpoints['inproc'].address),
            "ipc":
            ZmqEndpoint("connect", "ipc://%s" % zmq_ipc_fn),
            "tcp":
            ZmqEndpoint("connect", "tcp://*:%d" % zmq_tcp_port)})

    def run(self):
        if self.cid is not None:
            result = self.workflow.generate_data_for_master()
            self._zmq_socket.reply(self.cid, result)
        self.cid, self.output = self._queue.get()

    def stop(self):
        self.receive_data(None, None)

    def receive_data(self, cid, data):
        self._queue.put_nowait((cid, data))

    def apply_data_from_slave(self, data, slave):
        self._endpoints[slave.id] = (slave, data["ZmqLoaderEndpoints"])

    def apply_data_from_master(self, data):
        pass

    def generate_data_for_master(self):
        return {"ZmqLoaderEndpoints": self._endpoints}

    def generate_data_for_slave(self, slave):
        return None

    def drop_slave(self, slave):
        if slave.id in self._endpoints:
            del self._endpoints[slave.id]
