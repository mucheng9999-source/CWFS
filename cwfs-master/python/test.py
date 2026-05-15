
from lsst.cwfs.instrument import Instrument
from lsst.cwfs.algorithm import Algorithm
from lsst.cwfs.image import readFile, Image
import lsst.cwfs.plots as plots

fieldXY = [0,0]

I1 = Image(readFile('F:/DeskTop/弯月镜主动支撑仿真/曲率传感/cwfs-master\cwfs-master/tests/testImages/AuxTel/I1_intra_20190912_HD21161_z05.fits'), fieldXY, Image.INTRA)
I2 = Image(readFile('F:/DeskTop/弯月镜主动支撑仿真/曲率传感/cwfs-master\cwfs-master/tests/testImages/AuxTel/I2_extra_20190912_HD21161_z05.fits'), fieldXY, Image.EXTRA)

plots.plotImage(I1.image,'intra')
plots.plotImage(I2.image,'extra')

inst=Instrument('AuxTel',I1.sizeinPix)
algo=Algorithm('exp',inst,0)
algo.runIt(inst,I1,I2,'onAxis')
print(algo.zer4UpNm)
plots.plotZer(algo.zer4UpNm,'nm')
print(algo.zer4UpNm)
plots.plotImage(algo.Wconverge,'Final wavefront')