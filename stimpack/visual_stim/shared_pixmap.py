from multiprocessing import shared_memory
import numpy as np
import time
import sched
import threading

class SharedPixMapStimulus:
    def __init__(self, memname, shape=None):
        self.memname = memname
        if shape is not None:
            dummy = np.ones(shape).astype(np.uint8)
            self.reserve_memblock(dummy)
        else:
            print('SharedPixMapStimulus initialized without shape, waiting for frame')

    def reserve_memblock(self,frame):
        self.frame_shape = frame.shape
        self.frame_bytes = frame.nbytes
        self.frame_dtype = frame.dtype

        zz = np.zeros((10))

        self.memblock = shared_memory.SharedMemory(create=True,size=self.frame_bytes,name=self.memname)
        self.recblock = shared_memory.SharedMemory(create=True,size=zz.nbytes,name=self.memname+'_rec')

        self.global_frame = np.ndarray(self.frame_shape, dtype = self.frame_dtype, buffer=self.memblock.buf)
        self.global_frame[:] = np.zeros(self.frame_shape)

    def close(self):
        # Cancel any pending scheduled frames so the writer thread's scheduler returns promptly
        # (otherwise it runs until every remaining frame fires, up to `dur` seconds), then join it
        # so nothing is writing into the block while we tear it down.
        scheduler = getattr(self, 's', None)
        if scheduler is not None:
            for event in list(scheduler.queue):
                try:
                    scheduler.cancel(event)
                except ValueError:
                    pass
        thread = getattr(self, 'thread', None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        # Drop the ndarray view into the shared buffer before closing; otherwise SharedMemory.close()
        # raises BufferError ("cannot close exported pointers exist") and the segments leak in /dev/shm.
        self.global_frame = None
        for block in (getattr(self, 'memblock', None), getattr(self, 'recblock', None)):
            if block is not None:
                block.close()
                block.unlink()

    def genframe(self):
        '''
        To be overwritten
        '''
        pass
        
    def load_stream(self):
        self.s = sched.scheduler(time.time, time.sleep)
        self.thread = threading.Thread(target=self.s.run, daemon=True)

    def start_stream(self):
        self.t = time.time()
        # Anchor frame deadlines to stream START, not load time. sched.enter() fixes the absolute
        # deadline when it is called, so scheduling at load time made the stream fire a catch-up
        # burst and stop updating (self.t - load_time) seconds early. enterabs anchors to now.
        tis = np.arange(0, self.dur, 1/self.nominal_frame_rate)
        tis = tis[1:]
        for ti in tis:
            self.s.enterabs(self.t + ti, 1, self.genframe)
        self.thread.start()

class WhiteNoise(SharedPixMapStimulus):
    def __init__(self, memname, frame_shape, nominal_frame_rate, dur, seed=37, coverage='full'):
        super().__init__(memname = memname, shape=frame_shape)

        self.coverage=coverage
        self.nominal_frame_rate = nominal_frame_rate
        self.dur = dur
        self.seed = seed
        dummy = np.zeros((frame_shape[0], frame_shape[1], 3))*255
        dummy = dummy.astype(np.uint8)

        self.load_stream()

    
    def genframe(self):

        t = time.time()-self.t
        seed = int(round(self.seed + t*self.nominal_frame_rate)) # slightly risky, as t could be imprecise with PixMap approach
        np.random.seed(seed)
        img = np.random.rand(self.frame_shape[0], self.frame_shape[1])

        img_int = img*255/2+10
        img_int = img_int.astype(np.uint8)
            
        if self.coverage=='left':
            img_int[:,:int(img_int.shape[1]/2)] = 0
        self.global_frame[:,:,0] = img_int
        self.global_frame[:,:,1] = img_int
        self.global_frame[:,:,2] = img_int

