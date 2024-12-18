import ctk
import qt

from slicer.ScriptedLoadableModule import *
from slicer.i18n import tr as _
from slicer.i18n import translate
from DICOMLib import DICOMUtils

# This module takes a DICOM directory and outputs NRRD files for each patient
# series into a DICOM conforming folder hierarchy Patient/Study/Series.
class DICOMToNRRD(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("DICOM To NRRD")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Utilities")]
        self.parent.dependencies = ["DICOM"]
        self.parent.contributors = ["Alex Myers (Virtual Dentistry, LLC)"]
        self.parent.helpText = _("""Batch processing for converting DICOM files
            into NRRD files using a DICOM folder hierarchy of patient, study, and series names.""")
        self.parent.helpText += parent.defaultDocumentationLink
        self.parent.acknowledgementText = _("""This file was originally developed by Alex Myers of Virtual Dentistry, LLC.""")


# DICOMToNRRDWidget for the DICOM To NRRD Slicer module
class DICOMToNRRDWidget(ScriptedLoadableModuleWidget):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    # Setup the DICOM To NRRD Module GUI
    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        # Drop down Parameters menu
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = _("Parameters")
        self.layout.addWidget(parametersCollapsibleButton)

        # Layout with the collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        self.inputDirSelector = ctk.ctkPathLineEdit()
        self.inputDirSelector.filters = ctk.ctkPathLineEdit.Dirs
        self.inputDirSelector.settingKey = "DICOMToNRRDInputDir"
        parametersFormLayout.addRow(_("Input DICOM directory:"), self.inputDirSelector)

        self.outputDirSelector = ctk.ctkPathLineEdit()
        self.outputDirSelector.filters = ctk.ctkPathLineEdit.Dirs
        self.outputDirSelector.settingKey = "DICOMToNRRDOutputDir"
        parametersFormLayout.addRow(_("Output NRRD directory:"), self.outputDirSelector)

        self.dicomMetadataCheckBox = qt.QCheckBox()
        self.dicomMetadataCheckBox.checked = True
        self.dicomMetadataCheckBox.setToolTip(_("Produce JSON file/s with DICOM and volume information for each patient series"))
        parametersFormLayout.addRow(_("Create DICOM information file/s:"), self.dicomMetadataCheckBox)

        self.scalarVolumesCheckBox = qt.QCheckBox()
        self.scalarVolumesCheckBox.checked = False
        self.scalarVolumesCheckBox.setToolTip(_("Only produce NRRD files for scalar volumes only. " + 
            "When checked this excludes segmentation and structure sets."))
        parametersFormLayout.addRow(_("NRRD Scalar Volumes Only:"), self.scalarVolumesCheckBox)        
        
        # Batch Process Button        
        self.processButton = qt.QPushButton(_("Process"))
        self.processButton.toolTip = _("Batch process DICOM files to NRRD files with a patient, study, series folder hierarchy")
        parametersFormLayout.addRow(self.processButton)

        # connections
        self.processButton.connect("clicked(bool)", self.onProcessButton)

        self.statusLabel = qt.QPlainTextEdit()
        self.statusLabel.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
        parametersFormLayout.addRow(self.statusLabel)

        # Add vertical spacer
        self.layout.addStretch(1)    

    # Process button callback triggered when the Process button is clicked
    def onProcessButton(self):
        try:
            with slicer.util.tryWithErrorDisplay(_("Unexpected error."), waitCursor=True):
                if not self.outputDirSelector.currentPath:
                    self.outputDirSelector.currentPath = tempfile.mkdtemp(prefix="DICOMToNRRD-", dir=slicer.app.temporaryPath)

                self.inputDirSelector.addCurrentPathToHistory()
                self.outputDirSelector.addCurrentPathToHistory()
                self.statusLabel.plainText = ""

                # Main logic
                dicomDataDir = self.inputDirSelector.currentPath
                nrrdDir = self.outputDirSelector.currentPath
                self.logic = DICOMToNRRDLogic()
                self.logic.logCallback = self.addLog
                self.logic.DICOMToNRRDProcessing(dicomDataDir, nrrdDir, self.dicomMetadataCheckBox.checked, self.scalarVolumesCheckBox.checked)
        except Exception as err:
            self.logic.PrintException(err)

    # Nothing to cleanup, just pass
    def cleanup(self):
        pass

    # Add to the log window
    def addLog(self, text):
        """Append text to log window"""
        self.statusLabel.appendPlainText(text)
        slicer.app.processEvents()  # force update of the text field

import os
import datetime
import json
import re
import slicer
import logging

# Logic for converting DICOM data to a NRRD file
class DICOMToNRRDLogic(ScriptedLoadableModuleLogic):
    """
    Uses ScriptedLoadableModuleLogic base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    # set logCallback to None for this logic class
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.logCallback = None

    # callback to the widget log in this case
    def addLog(self, text):
        logging.info(text)
        if self.logCallback:
            self.logCallback(text)

    # Save a specific NRRD file for a selected patient
    def SaveNRRDFile(self, patientSeriesDir, patientName, node):
        nrrdFilename = slicer.app.ioManager().forceFileNameValidCharacters(patientName) + ".nrrd"
        # Save nrrd file
        self.addLog(f'Successfully processed {patientName}')
        # Keep the underscores for NRRD for any parsing for transferring the file
        success = slicer.util.saveNode(node, patientSeriesDir + "/" + nrrdFilename)
        
    # Convert a string to alpha numeric characters only
    def AlphaNumericCharactersOnly(self, str):
        parsedString = re.sub(r'[^A-Za-z0-9 ]+', '', str)
        return parsedString

    # Save DICOM information and write a PatientDICOMInfo.json for a patient series
    def SaveJsonFile(self, patientSeriesDir, instUid):
        """ Generate a dictionary of patient DICOM information for the series """
        dictionary = {
            # DICOM header meta information
            'FileMetaInformationGroupLength': slicer.dicomDatabase.instanceValue(instUid, '0002,0000'),
            'FileMetaInformationVersion': slicer.dicomDatabase.instanceValue(instUid, '0002,0001'),
            'MediaStorageSOPClassUID': slicer.dicomDatabase.instanceValue(instUid, '0002,0002'),
            'MediaStorageSOPInstanceUID': slicer.dicomDatabase.instanceValue(instUid, '0002,0003'),
            'TransferSyntaxUID': slicer.dicomDatabase.instanceValue(instUid, '0002,0010'),
            'ImplementationClassUID': slicer.dicomDatabase.instanceValue(instUid, '0002,0012'),
            'ImplementationVersionName': slicer.dicomDatabase.instanceValue(instUid, '0002,0013'),
            'SourceApplicationEntityTitle': slicer.dicomDatabase.instanceValue(instUid, '0002,0016'),

            # DICOM dataset information
            'SpecificCharacterSet': slicer.dicomDatabase.instanceValue(instUid, '0008,0005'),
            'ImageType': slicer.dicomDatabase.instanceValue(instUid, '0008,0008'),
            'SOPClassUID': slicer.dicomDatabase.instanceValue(instUid, '0008,0016'),
            'SOPInstanceUID': slicer.dicomDatabase.instanceValue(instUid, '0008,0018'),
            'StudyDate': slicer.dicomDatabase.instanceValue(instUid, '0008,0020'),
            'SeriesDate': slicer.dicomDatabase.instanceValue(instUid, '0008,0021'),
            'ContentDate': slicer.dicomDatabase.instanceValue(instUid, '0008,0023'),
            'StudyTime': slicer.dicomDatabase.instanceValue(instUid, '0008,0030'),
            'SeriesTime': slicer.dicomDatabase.instanceValue(instUid, '0008,0031'),
            'ContentTime': slicer.dicomDatabase.instanceValue(instUid, '0008,0033'),
            'AccessionNumber': slicer.dicomDatabase.instanceValue(instUid, '0008,0050'),
            'Modality': slicer.dicomDatabase.instanceValue(instUid, '0008,0060'),
            'Manufacturer': slicer.dicomDatabase.instanceValue(instUid, '0008,0070'),
            'ReferringPhysicianName': slicer.dicomDatabase.instanceValue(instUid, '0008,0090'),
            'StudyDescription': slicer.dicomDatabase.instanceValue(instUid, '0008,1030'),
            'SeriesDescription': slicer.dicomDatabase.instanceValue(instUid, '0008,103E'),
            'PhysiciansReadingStudy': slicer.dicomDatabase.instanceValue(instUid, '0008,1060'),
            'ManufacturerModelName': slicer.dicomDatabase.instanceValue(instUid, '0008,1090'),
            'PatientName': slicer.dicomDatabase.instanceValue(instUid, '0010,0010'),
            'PatientID': slicer.dicomDatabase.instanceValue(instUid, '0010,0020'),
            'PatientBirthDate': slicer.dicomDatabase.instanceValue(instUid, '0010,0030'),
            'PatientSex': slicer.dicomDatabase.instanceValue(instUid, '0010,0040'),
            'PatientComments': slicer.dicomDatabase.instanceValue(instUid, '0010,4000'),
            'SliceThickness': slicer.dicomDatabase.instanceValue(instUid, '0018,0050'),
            'PatientPosition': slicer.dicomDatabase.instanceValue(instUid, '0018,5100'),
            'StudyInstanceUID': slicer.dicomDatabase.instanceValue(instUid, '0020,000D'),
            'SeriesInstanceUID': slicer.dicomDatabase.instanceValue(instUid, '0020,000E'),
            'StudyID': slicer.dicomDatabase.instanceValue(instUid, '0020,0010'),
            'SeriesNumber': slicer.dicomDatabase.instanceValue(instUid, '0020,0011'),
            'InstanceNumber': slicer.dicomDatabase.instanceValue(instUid, '0020,0013'),
            'ImagePositionPatient': slicer.dicomDatabase.instanceValue(instUid, '0020,0032'),
            'ImageOrientationPatient': slicer.dicomDatabase.instanceValue(instUid, '0020,0037'),
            'FrameOfReferenceUID': slicer.dicomDatabase.instanceValue(instUid, '0020,0052'),
            'ImagesInAcquisition': slicer.dicomDatabase.instanceValue(instUid, '0020,1002'),
            'PositionReferenceIndicator': slicer.dicomDatabase.instanceValue(instUid, '0020,1040'),
            'SamplesPerPixel': slicer.dicomDatabase.instanceValue(instUid, '0028,0002'),
            'PhotometricInterpretation': slicer.dicomDatabase.instanceValue(instUid, '0028,0004'),
            'Rows': slicer.dicomDatabase.instanceValue(instUid, '0028,0010'),
            'Columns': slicer.dicomDatabase.instanceValue(instUid, '0028,0011'),
            'PixelSpacing': slicer.dicomDatabase.instanceValue(instUid, '0028,0030'),
            'BitsAllocated': slicer.dicomDatabase.instanceValue(instUid, '0028,0100'),
            'BitsStored': slicer.dicomDatabase.instanceValue(instUid, '0028,0101'),
            'HighBit': slicer.dicomDatabase.instanceValue(instUid, '0028,0102'),
            'PixelRepresentation': slicer.dicomDatabase.instanceValue(instUid, '0028,0103'),
            'WindowCenter': slicer.dicomDatabase.instanceValue(instUid, '0028,1050'),
            'WindowWidth': slicer.dicomDatabase.instanceValue(instUid, '0028,1051'),
            'RescaleIntercept': slicer.dicomDatabase.instanceValue(instUid, '0028,1052'),
            'RescaleSlope': slicer.dicomDatabase.instanceValue(instUid, '0028,1053'),
            'RescaleType': slicer.dicomDatabase.instanceValue(instUid, '0028,1054'),
            'PersonsAddress': slicer.dicomDatabase.instanceValue(instUid, '0040,1102'),
            'PersonsTelephone': slicer.dicomDatabase.instanceValue(instUid, '0040,1103')
        }

        jsonFile = patientSeriesDir + "/PatientDICOMInfo.json"
        json_object = json.dumps(dictionary, indent=4)
        # Write JSON file
        with open(jsonFile, 'w') as f:
            f.write(json_object)

    # Create the patient series directory only if it exists
    def CreatePatientSeriesDirectory(self, patientSeriesDir):
        if not os.path.exists(patientSeriesDir):
            os.makedirs(patientSeriesDir)

    # Create a patient name directory based on patient name and UID in case you have patients with the same first and last names
    # As a fail safe, create a dummy patient name with the current date
    def PatientName(self, db, patientUID, shNode, patientItem):
        """ patientUID is unique in case of patients with the same first and last names """
        patientName = db.nameForPatient(patientUID) + " " + shNode.GetItemAttribute(patientItem, 'DICOM.PatientID')
        if patientName == "":
            patientName = "Patient " + DateNowPrettyFormat()
        return patientName

    # Compose a study name for the patient
    def PatientStudyName(self, shNode, studyItem):
        studyText = shNode.GetItemAttribute(studyItem, 'DICOM.StudyDate')
        if studyText == "":
            studyText = shNode.GetItemAttribute(studyItem, 'DICOM.StudyID')
        if studyText == "":
            studyText = shNode.GetItemAttribute(studyItem, 'DICOM.StudyDescription')
        studyText = self.AlphaNumericCharactersOnly(studyText)
        # Study Description comes back with "No study description" when there is no study
        return studyText

    # Formulate a patient series name
    def PatientSeriesName(self, shNode, seriesItem):
        seriesName = shNode.GetItemAttribute(seriesItem, 'DICOM.SeriesNumber')
        if seriesName == "":
            seriesName = shNode.GetItemAttribute(seriesItem, 'DICOM.SeriesDescription')
        seriesName = self.AlphaNumericCharactersOnly(seriesName)
        if seriesName == "":
            seriesName = self.DateNowPrettyFormat()
        return seriesName

    # Use unique format down to the microsecond in case there are no study, series, or patient names available
    # The microsecond will make the series unique. E.g. output: July 20, 2023 14-34-281578
    def DateNowPrettyFormat(self):
        hourMinute = datetime.datetime.now().strftime("%H-%M-%f") # Hour-minute-microsecond format
        monthDayYear = datetime.date.today().strftime("%B %d, %Y") # Month day, Year format
        dateFormat = monthDayYear + " " + hourMinute
        return dateFormat

    # Print the Python Exception string and type of error
    def PrintException(self, err):
        self.addLog("Error processing DICOM data: " + str(err) + " error type: " + str(type(err)))
    
    # Print the Exception, patient name, study name, and series name for easier debugging
    def PrintError(self, err, patientName, studyName, seriesName):
        self.PrintException(err)
        self.addLog("Failed to process " + patientName + " study " + studyName + " series " + seriesName)
    
    # Validate the image data and scalar volume checkbox
    def ValidationChecks(self, processScalarVolumesOnly, instUid, patientName, studyName, seriesName, node):
        try:                                                            
            # Should this load be null from failed loading, return False for a failed validation
            if not node:
                return False
            
            # Only export images that are volumes
            if processScalarVolumesOnly == True:
                 if node.IsA('vtkMRMLScalarVolumeNode'):
                    return True
            
            return True;            
        except Exception as err:
            self.PrintError(err, patientName, studyName, seriesName)
            return False                

    # Primary processing that takes DICOM files and converts them to NRRD files
    def DICOMToNRRDProcessing(self, dicomDataDir, nrrdDir, writeDICOMMetaData, processScalarVolumesOnly):
        try:
            self.addLog("Processing " + dicomDataDir)
            loadedNodeIDs = []  # this list will contain the list of all loaded node IDs        
            with DICOMUtils.TemporaryDICOMDatabase() as db:
                DICOMUtils.importDicom(dicomDataDir, db)  # load the DICOM files into a Slicer DB            
                patientUIDs = db.patients()  
                if len(patientUIDs) > 0:                    
                    for patientUID in patientUIDs:  
                        # Raise a loading Exception for a single patient to allow the script
                        # to continue processing other patients
                        try:
                            loadedNodeIDs = DICOMUtils.loadPatientByUID(patientUID)
                            for loadedNodeID in loadedNodeIDs:
                                # Raise Exception for a single series within the for loop since
                                # other patient series within a study may not raise an Exception
                                try:
                                    # Check if we want to save this node
                                    node = slicer.mrmlScene.GetNodeByID(loadedNodeID)                                                       
                                    # Fetch items
                                    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
                                    seriesItem = shNode.GetItemByDataNode(node)
                                    studyItem = shNode.GetItemParent(seriesItem)
                                    patientItem = shNode.GetItemParent(studyItem)
                                    seriesInstanceUID = shNode.GetItemUID(seriesItem, 'DICOM')
                                    instUids = slicer.dicomDatabase.instancesForSeries(seriesInstanceUID)                        

                                    # Construct unique patient file name
                                    patientName = self.PatientName(db, patientUID, shNode, patientItem)                        
                                    studyName = self.PatientStudyName(shNode, studyItem)                        
                                    seriesName = self.PatientSeriesName(shNode, seriesItem)                     
                                        
                                    if self.ValidationChecks(processScalarVolumesOnly, instUids[0], patientName, studyName, seriesName, node) == True:                                                                                                

                                        self.addLog("Processing patientName: " + patientName + " series " + seriesName)
                                        
                                        processedPatientNameDir = nrrdDir + "/" + patientName + "/"
                                        patientSeriesDir = processedPatientNameDir + studyName + "/" + seriesName + "/"                                                                                                                                                          
                                                                
                                        # Create patient series directory
                                        self.CreatePatientSeriesDirectory(patientSeriesDir)                        
                                                                                
                                        # Write NRRD file
                                        self.SaveNRRDFile(patientSeriesDir, patientName, node)                        

                                        # Write Patient Info JSON File
                                        if writeDICOMMetaData:                            
                                            self.SaveJsonFile(patientSeriesDir, instUids[0])
                                    
                                except Exception as err:
                                    self.PrintError(err, patientName, studyName, seriesName);
                                    continue
                        except Exception as err:
                            self.PrintException(err)   
                            continue

            slicer.util.infoDisplay("DICOM to NRRD processing finished")
        except Exception as err:
            self.PrintException(err)            
            


import shutil
import tempfile
import glob
import os

# Test converting DICOM data to a NRRD file
class DICOMToNRRDTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def runTest(self):
        self.test_DICOMToNRRD()

    # Test out the DICOM data from the CTHeadAxialDicom
    def test_DICOMToNRRD(self):
        # Copy all the .dcm files to a DICOM folder
        dicomTestDir = slicer.util.sourceDir() + "/Testing/Data/Input/CTHeadAxialDicom/"
        self.assertTrue(os.path.exists(dicomTestDir))

        # Make a temporary output NRRD directory
        nrrdTestDir = slicer.app.slicerHome + "/Testing/Temporary/NRRD/"
        if not os.path.exists(nrrdTestDir):
            os.makedirs(nrrdTestDir)

        self.assertTrue(os.path.isdir(nrrdTestDir))

        logic = DICOMToNRRDLogic()
        logic.DICOMToNRRDProcessing(dicomTestDir, nrrdTestDir, True, False)

        # Test to ensure the NRRD file was created along with the PatientDICOMInfo file
        austrialiaSeries = nrrdTestDir + "Austrialian 8775070/20090102/123456/"
        nrrdFile = austrialiaSeries + "Austrialian 8775070.nrrd"
        patientDICOMInfoFile = austrialiaSeries + "PatientDICOMInfo.json"
        self.assertTrue(os.path.isfile(nrrdFile))
        self.assertTrue(os.path.isfile(patientDICOMInfoFile))

        # remove the NRRD directory and then re-test without writing the JSON file
        shutil.rmtree(nrrdTestDir)

        logic.DICOMToNRRDProcessing(dicomTestDir, nrrdTestDir, False, True)

        self.assertTrue(os.path.isfile(nrrdFile))
        self.assertFalse(os.path.isfile(patientDICOMInfoFile))

        # remove the temporary NRRD test directory for cleanup
        shutil.rmtree(nrrdTestDir)
