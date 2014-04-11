#! /usr/bin/env vtkpython

#
#  Script to take a Dicom series and generate an STL surface mesh.
#
#  Written by David T. Chen from the National Library of Medicine, dchen@mail.nih.gov.
#  It is covered by the Apache License, Version 2.0:
#      http://www.apache.org/licenses/LICENSE-2.0
#

import sys, os, zipfile, tempfile, getopt, math, time, gc


# Global variables
#
verbose          = 0
debug            = 0

zipFlag          = False
dicomString      = ""
cleanUp          = True

isovalue         = 0
CTonly           = False
doubleThreshold  = False
thresholds       = []
tissueType       = ""
shrinkFlag       = True

smoothIterations = 25
quad             = .90
outname          = "result.stl"
connectivityFilter = False
anisotropicSmoothing = False
medianFilter     = False
metadataFile     = ""

options = []



def usage():
    print
    print ("dicom2stl.py: [options] dicom.zip")
    print ("   or")
    print ("dicom2stl.py: [options] volume_image")
    print ("   or")
    print ("dicom2stl.py: [options] slice1 ... sliceN")
    print
    print ("    -h, --help           This help message")
    print ("    -v, --verbose        Verbose output")
    print ("    -D, --debug          Debug mode")
    print
    print ("    -o string            Output file name (default=result.stl)")
    print ("    -m string            Metadata file name (default=\"\")")
    print ("    -t string, --type string        CT Tissue type [skin, bone, soft_tissue, fat]")
    print ("    -c, --clean          Clean up temp files")
    print ("    --ct                 Only allow CT images")
    print
    print ("    -s string, --search string    Dicom series search string")
    print ("    -l, --largest        Keep only the largest connected mesh")
    print ("    -a, --anisotropic    Apply anisotropic smoothing to the volume")
    print ("    -i value, --isovalue value    Iso-surface value")
    print ("    -d string, --double string    Double threshold with 4 values in a string seperated by semicolons")
    print
    print ("  Enable/Disable various filtering options")
    print ("    --disable string     Disable an option [anisotropic, shrink, median, largest]")
    print ("    --enable  string     Enable an option [anisotropic, shrink, median, largest]")


# Parse the command line arguments
#

try:
    opts, args = getopt.getopt(sys.argv[1:], "vDhacli:s:t:d:o:m:",
        [ "verbose", "help", "debug", "anisotropic", "clean", "ct", "isovalue=", "search=", "type=",
          "double=", "disable=", "enable=", "largest", "metadata"] )
except getopt.GetoptError, err:
    print (str(err))
    usage()
    sys.exit(2)


for o, a in opts:
    if o in ("-v", "--verbose"):
        verbose = verbose + 1
    elif o in ("-D", "--debug"):
        print "Debug"
        debug = debug + 1
        cleanFlag = False
    elif o in ("-h", "--help"):
        usage()
        sys.exit()
    elif o in ("-c", "--clean"):
        cleanUp = True
    elif o in ("-a", "--anisotropic"):
        anisotropicSmoothing = True
    elif o in ("-i", "--isovalue"):
        isovalue = float(a)
    elif o in ("--ct"):
        CTonly = True
    elif o in ("-l", "--largest"):
        connectivityFilter = True
    elif o in ("-s", "--search"):
        dicomString = a
    elif o in ("-t", "--type"):
        tissueType = a
        doubleThreshold = True
    elif o in ("-o", "--output"):
        outname = a
    elif o in ("-m", "--metadata"):
        metadataFile = a
    elif o in ("-d", "--double"):
        vals = a.split(';')
        for v in vals:
            thresholds.append(float(v))
        thresholds.sort()
        doubleThreshold = True
    elif o in ("--disable"):
        options.append("no"+a)
    elif o in ("--enable"):
        options.append(a)
    else:
        assert False, "unhandled options"

# Handle enable/disable options

for x in options:
    val = True
    y = x
    if x[:2] == "no":
        val = False
        y = x[2:]
    if y.startswith("shrink"):
        shrinkFlag = val
    if y.startswith("aniso"):
        anisotropicSmoothing = val
    if y.startswith("median"):
        medianFilter = val
    if y.startswith("large"):
        connectivityFilter = val


print
tempdir = tempfile.mkdtemp()
print "Temp dir: ", tempdir

if tissueType:
    # Convert tissue type name to threshold values
    print "Tissue type: ", tissueType
    if tissueType.find("bone") > -1:
        thresholds = [200., 800., 1300., 1500.]
    elif tissueType.find("skin") > -1:
        thresholds = [-200., 0., 500., 1500.]
    elif tissueType.find("soft") > -1:
        thresholds = [-15., 30., 58., 100.]
        medianFilter = True
    elif tissueType.find("fat") > -1:
        thresholds = [-122., -112., -96., -70.]
        medianFilter = True


if doubleThreshold:
   # check that there are 4 threshold values.
   print "Thresholds: ", thresholds
   if len(thresholds) != 4:
       print "Error: Threshold is not of size 4.", thresholds
       sys.exit(3)
else:
    print "Isovalue = ", isovalue


fname = args

if len(fname) == 0:
    print "Error: no input given."
    sys.exit(4)

if zipfile.is_zipfile(fname[0]):
    zipFlag = True



if verbose:
    print "File names: ", fname, "\n"
else:
    l = len(fname)
    if l>1:
        print "File names: ", fname[0], fname[1], "...", fname[l-1], "\n"
    else:
        print "File names: ", fname, "\n"

import SimpleITK as sitk

if debug:
    print "SimpleITK version: ", sitk.Version.VersionString()
    print "SimpleITK: ", sitk, "\n"

img      = sitk.Image( 100,100,100, sitk.sitkUInt8 )
dcmnames = []
metasrc  = img


#  Unzip a zipfile of dicom images into a temp directory
#
def loadZipDicom(name):
    print "Reading Dicom zip file:", name
    myzip = zipfile.ZipFile(name, 'r')
    fnames = myzip.namelist()

    for x in fnames:
        basename = os.path.basename(x)
        if len(basename):
            if basename[0] == '.':
                continue
        else:
            continue

        if (x.endswith(".dcm")) and (dicomString in x):
            dcmnames.append(x)

    if verbose:
        if verbose>1:
            print dcmnames
        else:
            l = len(dcmnames)
            print l, "files"
            print "[", dcmnames[0], dcmnames[1], " ... ", dcmnames[l-1], "]"

    try:
        myzip.extractall(tempdir)
    except:
        print "Zip extract failed"
    savedir = os.getcwd()
    lsdir = os.listdir(tempdir)
    os.chdir(tempdir)
    try:
        img = sitk.ReadImage( dcmnames )
    except:
        print "SimpleITK ReadImage failed on Dicom series"
    os.chdir(savedir)
    return img



#  Load our Dicom data
#
if zipFlag:
    # Case for a zip file of images
    if verbose:
        print "zip"
    img = loadZipDicom( fname[0] )
    firstslice = sitk.ReadImage(tempdir+"/"+dcmnames[0])
    metasrc = firstslice


else:
    # Case for a single volume image
    if len(fname) == 1:
        if verbose:
            print "Reading volume: ", fname[0]
        img = sitk.ReadImage( fname[0] )
        metasrc = img
    else:
    # Case for a series of image files
        if verbose:
            if verbose>1:
                print "Reading images: ", fname
            else:
                l = len(fname)
                print "Reading images: ", fname[0], fname[1], "...", fname[l-1]
        img = sitk.ReadImage( fname )
        firstslice = sitk.ReadImage( fname[0] )
        metasrc = firstslice

if CTonly and ( (sitk.Version.MinorVersion()>8) or (sitk.Version.MajorVersion()>0) ):
    # Check the metadata for CT image type.  Note that this only works with
    # SimpleITK version 0.8.0.  For earlier versions there is no GetMetaDataKeys method
    modality = "CT"
    modalitykey = "0008|0060"
    try:
        datadic = metasrc.GetMetaDataKeys()
        if modalitykey in datadic:
             modality = metasrc.GetMetaData("0008|0060")
        if debug:
             print datadic
    except AttributeError:
        print "Warning: could not access dicom meta-data"

    if modality.find("CT") == -1:
        print "Imaging modality is not CT.  Exiting."
        sys.exit(1)


#vtkname =  tempdir+"/vol0.vtk"
#sitk.WriteImage( img, vtkname )

def roundThousand(x):
    y = int(1000.0*x+0.5)
    return str(float(y)* .001)

def elapsedTime(start_time):
    dt = roundThousand(time.clock()-start_time)
    print "    ", dt, "seconds"

# Write out the metadata text file
#
if len(metadataFile):
    FP = open(metadataFile, "w")
    size = img.GetSize()
    spacing = img.GetSpacing()
    FP.write('xdimension ' + str(size[0]) + '\n')
    FP.write('ydimension ' + str(size[1]) + '\n')
    FP.write('zdimension ' + str(size[2]) + '\n')
    FP.write('xspacing ' + roundThousand(spacing[0]) + '\n')
    FP.write('yspacing ' + roundThousand(spacing[1]) + '\n')
    FP.write('zspacing ' + roundThousand(spacing[2]) + '\n')
    FP.close()


#
# shrink the volume to 256 cubed
if shrinkFlag:
    sfactor = []
    size = img.GetSize()
    sum = 0
    for s in size:
        x = int(math.ceil(s/256.0))
        sfactor.append( x )
        sum = sum + x

    if sum>3:
        # if sum==3, no shrink happens
        t = time.clock()
        print "Shrink factors: ", sfactor
        img = sitk.Shrink(img, sfactor)
        newsize = img.GetSize()
        print size, "->", newsize
        elapsedTime(t)

gc.collect()


# Apply anisotropic smoothing to the volume image.  That's a smoothing filter
# that preserves edges.
#
if anisotropicSmoothing:
    print "Anisotropic Smoothing"
    t = time.clock()
    pixelType = img.GetPixelID()
    img = sitk.Cast(img, sitk.sitkFloat32)
    img = sitk.CurvatureAnisotropicDiffusion(img, .03)
    img = sitk.Cast(img, pixelType)
    elapsedTime(t)
    gc.collect()

# Apply the double threshold filter to the volume
#
if doubleThreshold:
    print "Double Threshold"
    t = time.clock()
    img = sitk.DoubleThreshold(img, thresholds[0], thresholds[1], thresholds[2], thresholds[3], 255, 0)
    isovalue = 64.0
    elapsedTime(t)
    gc.collect()

# Apply a 3x3x1 median filter.  I only use 1 in the Z direction so it's not so slow.
#
if medianFilter:
    print "Median filter"
    t = time.clock()
    img = sitk.Median(img, [3,3,1])
    elapsedTime(t)
    gc.collect()

# Pad black to the boundaries of the image
#
pad = [5,5,5]
img = sitk.ConstantPad(img, pad, pad)
gc.collect()

if verbose:
    print "\nImage for isocontouring"
    print img.GetSize()
    print img.GetPixelIDTypeAsString()
    print img.GetSpacing()
    print img.GetOrigin()
    if verbose>1:
        print img
    print

#vtkname =  tempdir+"/vol.vtk"
#sitk.WriteImage( img, vtkname )

import sitk2vtk
vtkimg = sitk2vtk.sitk2vtk(img)
img = None
gc.collect()

import traceback, vtk

if debug:
    print "\nVTK version: ", vtk.vtkVersion.GetVTKVersion()
    print "VTK: ", vtk, "\n"

import vtkutils

mesh = vtkutils.extractSurface(vtkimg, isovalue)
vtkimg = None
gc.collect()
mesh2 = vtkutils.cleanMesh(mesh, connectivityFilter)
mesh = None
gc.collect()
mesh3 = vtkutils.smoothMesh(mesh2, smoothIterations)
mesh2 = None
gc.collect()
mesh4 = vtkutils.reduceMesh(mesh3, quad)
mesh3 = None
gc.collect()
vtkutils.writeMesh(mesh4, outname)
mesh4 = None
gc.collect()


# remove the temp directory
import shutil
if cleanUp:
    shutil.rmtree(tempdir)

print