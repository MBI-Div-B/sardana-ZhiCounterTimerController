import time, os.path as path
from sardana import State
from sardana.pool.controller import CounterTimerController, Type, Description, DefaultValue

import re
import warnings
import numpy as np
from scipy.stats import sem

import zhinst.ziPython as zh
import zhinst.utils as utils

class boxcars:
    def __init__(self, ip='127.0.0.1', port=8004, api_level=6, device='dev2192',
                 iface='1GbE', settings='PumpUnpumpBoxCar.xml', repRate = 1500, timeOut = 30):
        # Create a connection to a Zurich Instruments Data Server
        
        self.daq = zh.ziDAQServer(ip, port, api_level)
        self.device = device
        self.iface = iface
        # one could also use utils.autoConnect() instead
        self.daq.connectDevice(self.device, self.iface)
        self.daq.connect()
        # load settings
        settings_path = path.join(utils.get_default_settings_path(self.daq),
                                  settings)
        utils.load_settings(self.daq, self.device, settings_path)
        
        self.timeOut      = timeOut
        self.acqStartTime = None
        self.acqEndTime   = None
        self.isAcquiring  = False
    
        # Detect a device
        #self.device = utils.autoDetect(self.daq)
        # Find out whether the device is an HF2 or a UHF
        self.devtype = self.daq.getByte('/%s/features/devtype' % self.device)
        self.options = self.daq.getByte('/%s/features/options' % self.device)
        self.clock   = self.daq.getDouble('/%s/clockbase' % self.device)

        if not re.search('BOX', self.options):
            raise Exception("This example can only be ran on a UHF with the BOX option enabled.")

        if self.daq.getConnectionAPILevel() != 6:
            warnings.warn("ziDAQServer is using API Level 1, it is strongly recommended " * \
                "to use API Level 6 in order to obtain boxcar data with timestamps.")
    
        self.daq.sync()
                
        self.daq.subscribe('/%s/boxcars/%d/sample' % (self.device, 0))
        self.daq.subscribe('/%s/boxcars/%d/sample' % (self.device, 1))
                
    def startAcq(self,intTime=1):
        self.isAcquiring = True
        self.acqStartTime = time.time()
        self.data = []
        
        self.pollData(intTime)

    def pollData(self, intTime):
        
        poll_length = intTime  # [s]
        poll_timeout = 500  # [ms]
        poll_flags = 0x0004
        poll_return_flat_dict = False
        
        self.daq.flush()      
        self.data = self.daq.poll(poll_length, poll_timeout, poll_flags, poll_return_flat_dict)
        self.isAcquiring = False
        self.acqEndTime = time.time()
        
    def readData(self): 
        boxcar1_value     = self.data[self.device]['boxcars']['0']['sample']['value']
        boxcar1_timestamp = self.data[self.device]['boxcars']['0']['sample']['timestamp']                                               
        
        boxcar2_value     = self.data[self.device]['boxcars']['1']['sample']['value']
        boxcar2_timestamp = self.data[self.device]['boxcars']['1']['sample']['timestamp']           
                
        maxStartTime = np.max([boxcar1_timestamp[0], boxcar2_timestamp[0]])	
        minFinishTime = np.min([boxcar1_timestamp[-1], boxcar2_timestamp[-1]])	
        
        
        select1 = (boxcar1_timestamp >= maxStartTime) &  (boxcar1_timestamp <= minFinishTime) & (~np.isnan(boxcar1_value))
        select2 = (boxcar2_timestamp >= maxStartTime) &  (boxcar2_timestamp <= minFinishTime) & (~np.isnan(boxcar2_value))
        
        freq     = 1/(np.mean((np.diff(boxcar1_timestamp[select1])))/self.clock)
        duration = self.acqEndTime-self.acqStartTime
        mean1 = np.mean(boxcar1_value[select1], dtype=np.float64)
        mean2 = np.mean(boxcar2_value[select2], dtype=np.float64)
        rel   = mean1/mean2
        diff  = abs(mean1-mean2)
        
        return (mean1, mean2,
                    sem(boxcar1_value[select1]),sem(boxcar2_value[select2]), len(boxcar1_value[select1]), freq, duration, rel, diff)     

    def close(self):
        # Unsubscribe from all paths
        self.daq.unsubscribe('*')
        del self.daq
        

class ZhiCounterTimerController(CounterTimerController):
    """The most basic controller intended from demonstration purposes only.
    This is the absolute minimum you have to implement to set a proper counter
    controller able to get a counter value, get a counter state and do an
    acquisition.

    This example is so basic that it is not even directly described in the
    documentation"""
    ctrl_properties = {'IP': {Type: str, Description: 'The IP of the ZHI controller', DefaultValue: '127.0.0.1'},
						     'port': {Type: int, Description: 'The port of the ZHI controller', DefaultValue: 8004},
                       'device': {Type: str, Description: 'Device name', DefaultValue: 'dev2192'},
                       'iface': {Type: str, Description: 'Device interface', DefaultValue: '1GbE'},
                       'settings': {Type: str, Description: 'Device Settings file name', DefaultValue: 'PumpUnpumpBoxCar'},
                       'repRate': {Type: int, Description: 'RepRate of the acquisition', DefaultValue: 1500},
                       'timeOut': {Type: int, Description: 'Timeout of the acquisition in s', DefaultValue: 30}}
       
    
    def AddDevice(self, axis):
        pass

    def DeleteDevice(self, axis):
        pass

    def __init__(self, inst, props, *args, **kwargs):
        """Constructor"""
        super(zhiCounterTimerController,
              self).__init__(inst, props, *args, **kwargs)
        print 'ZI Boxcar Initialization ...',
        self.zhi = boxcars(self.IP, self.port, api_level=6, device=self.device,
                           iface=self.iface, settings=self.settings,
                           repRate=self.repRate, timeOut=self.timeOut)
        print 'SUCCESS for device %s connected to dataserver %s:%d with settings %s' % (self.device, self.IP, self.port, self.settings)
        self.data = []
        self.isAquiring = False

    def ReadOne(self, axis):
        """Get the specified counter value"""
        if axis == 0:
            self.data = self.zhi.readData()
                   
        return self.data[axis]

    def StateOne(self, axis):
        """Get the specified counter state"""
        
        if self.zhi.isAcquiring:
            return State.Moving, "Counter is acquiring"
        else:
            return State.On, "Counter is stopped"
        
    def StartOne(self, axis, value=None):
        """acquire the specified counter"""
        if axis == 0:
            self.zhi.startAcq(value)
    
    def StartAll(self):
        pass
    
    def LoadOne(self, axis, value, repetitions):
        pass

    def StopOne(self, axis):
        """Stop the specified counter"""
        pass