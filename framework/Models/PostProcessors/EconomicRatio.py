# Copyright 2017 Battelle Energy Alliance, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Created on Aug 4, 2020

@author: ZHOUJ2, dgarrett622
"""
#External Modules---------------------------------------------------------------
import numpy as np
import xarray as xr
import scipy.stats as stats
#External Modules End-----------------------------------------------------------

#Internal Modules---------------------------------------------------------------
from .PostProcessorInterface import PostProcessorInterface
from .BasicStatistics import BasicStatistics
from utils import utils
from utils import InputData, InputTypes
#Internal Modules End-----------------------------------------------------------

class EconomicRatio(BasicStatistics):
  """
    EconomicRatio filter class. It computes economic metrics
  """

  # values from BasicStatistics
  scalarVals =   BasicStatistics.scalarVals
  vectorVals =   BasicStatistics.vectorVals
  steVals    =   BasicStatistics.steVals + ['valueAtRisk_ste']

  # economic/financial metrics
  econVals   = ['sharpeRatio',             #financial metric
                'sortinoRatio',            #financial metric
                'gainLossRatio',           #financial metric
                'valueAtRisk',             # Value at risk (alpha)
                'expectedShortfall'        # conditional value at risk (gammma)
                ]

  @classmethod
  def getInputSpecification(cls):
    """
      Method to get a reference to a class that specifies the input data for
      class cls.
      @ In, cls, the class for which we are retrieving the specification
      @ Out, inputSpecification, InputData.ParameterInput, class to use for
        specifying input of cls.
    """

    # get input specification from BasicStatistics (scalarVals and vectorVals)
    inputSpecification = super(EconomicRatio, cls).getInputSpecification()

    # add econVals
    for econ in cls.econVals:
      econSpecification = InputData.parameterInputFactory(econ,
                                                          contentType=InputTypes.StringListType)
      if econ in ["sortinoRatio", "gainLossRatio"]:
        econSpecification.addParam("threshold", InputTypes.StringType)
      elif econ in ["expectedShortfall", "valueAtRisk"]:
        econSpecification.addParam("threshold", InputTypes.FloatType)
      econSpecification.addParam("prefix", InputTypes.StringType)
      inputSpecification.addSub(econSpecification)

    return inputSpecification

  def __init__(self):
    """
      Constructor
      @ In, None
      @ Out, None
    """
    super().__init__()
    self.printTag = "PostProcessor ECONOMIC RATIO"

  def initialize(self, runInfo, inputs, initDict):
    """
      Method to initialize the EconomicRatio pp. In here the working dir is
      grepped.
      @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
      @ In, inputs, list, list of inputs
      @ In, initDict, dict, dictionary with initialization options
      @ Out, None
    """

    # construct a list of all the parameters that have requested values from scalarVals
    # and vectorVals into self.allUsedParams
    super().initialize(runInfo, inputs, initDict)

    # add a list of all the parameters that have requested values from econVals into
    # self.allUsedParams
    for metricName in self.econVals:
      if metricName in self.toDo.keys():
        for entry in self.toDo[metricName]:
          self.allUsedParams.update(entry["targets"])
          try:
            self.allUsedParams.update(entry["features"])
          except KeyError:
            pass

    # for backward compatibility, compile the full list of parameters used in EconomicRatio calculations
    self.parameters["targets"] = list(self.allUsedParams)
    inputObj = inputs[-1]  if type(inputs) == list else inputs
    if inputObj.type == "HistorySet":
      self.dynamic = True
    inputMetaKeys = []
    outputMetaKeys = []
    for metric, infos in self.toDo.items():
      if metric in self.econVals:
        steMetric = metric + "_ste"
        if steMetric in self.steVals:
          for info in infos:
            prefix = info["prefix"]
            for target in info["targets"]:
              if metric == 'valueAtRisk':
                for strThreshold in info['strThreshold']:
                  metaVar = prefix + '_' + strThreshold + '_ste_' + target if not self.outputDataset else metric + '_ste'
                  metaDim = inputObj.getDimensions(target)
                  if len(metaDim[target]) == 0:
                    inputMetaKeys.append(metaVar)
                  else:
                    outputMetaKeys.append(metaVar)
              else:
                metaVar = prefix + '_ste_' + target if not self.outputDataset else metric + '_ste'
                metaDim = inputObj.getDimensions(target)
                if len(metaDim[target]) == 0:
                  inputMetaKeys.append(metaVar)
                else:
                  outputMetaKeys.append(metaVar)
    metaParams = {}
    if not self.outputDataset:
      if len(outputMetaKeys) > 0:
        metaParams = {key:[self.pivotParameter] for key in outputMetaKeys}
    else:
      if len(outputMetaKeys) > 0:
        params = {}
        for key in outputMetaKeys + inputMetaKeys:
          # valueAtRisk standard error has additional index
          if key == "valueAtRisk_ste":
            params[key] = [self.pivotParameter, self.steMetaIndex, "threshold"]
          else:
            params[key] = [self.pivotParameter, self.steMetaIndex]
        metaParams.update(params)
      elif len(inputMetaKeys) > 0:
        params = {}
        for key in inputMetaKeys:
          # valueAtRisk standard error has additional index
          if key == "valueAtRisk_ste":
            params[key] = [self.pivotParameter, self.steMetaIndex, "threshold"]
          else:
            params[key] = [self.pivotParameter, self.steMetaIndex]
        metaParams.update(params)
    metaKeys = inputMetaKeys + outputMetaKeys
    self.addMetaKeys(metaKeys, metaParams)

  def _localReadMoreXML(self, xmlNode):
    """
      Function to read the portion of the xml input that belongs to this specialized class
      and initialize some stuff based on the inputs got
      @ In, xmlNode, xml.etree.Element, Xml element node
      @ Out, None
    """
    paramInput = self.getInputSpecification()()
    paramInput.parseNode(xmlNode)
    self._handleInput(paramInput)

  def _handleInput(self, paramInput):
    """
      Function to handle the parsed paramInput for this class.
      @ In, paramInput, ParameterInput, the already parsed input.
      @ Out, None
    """

    # handle scalarVals and vectorVals from BasicStatistics
    super()._handleInput(paramInput, childVals=self.econVals)

    # now handle econVals
    for child in paramInput.subparts:
      tag = child.getName()
      if tag in self.econVals:
        if "prefix" not in child.parameterValues:
          self.raiseAnError(IOError, "No prefix is provided for node: ", tag)
        # get the prefix
        prefix = child.parameterValues["prefix"]
        if tag in ["sortinoRatio", "gainLossRatio"]:
          # get targets
          targets = set(child.value)
          # if targets are not specified by user
          if len(targets) < 1:
            self.raiseAWarning("No targets were specified in text of <"+tag+">!  Skipping metric...")
            continue
          if tag not in self.toDo.keys():
            self.toDo[tag] = [] # list of {"targets": (), "prefix": str, "threshold": str}
          if "threshold" not in child.parameterValues:
            threshold = "zero"
          else:
            threshold = child.parameterValues["threshold"].lower()
            if threshold not in ["zero", "median"]:
              self.raiseAWarning("Unrecognized threshold in {}, prefix '{}' use zero instead!".format(tag, prefix))
              threshold = "zero"

          if "expectedValue" not in self.toDo.keys():
            self.toDo["expectedValue"] = []
          if "median" not in self.toDo.keys():
            self.toDo["median"] = []
          # add any expectedValue targets that are missing
          expectedValueToAdd = self._additionalTargetsToAdd("expectedValue", child.value)
          if len(expectedValueToAdd) > 0:
            self.toDo["expectedValue"].append({"targets": expectedValueToAdd, "prefix": "BSMean"})
          # add any median targets that are missing
          medianValueToAdd = self._additionalTargetsToAdd("median", child.value)
          if len(medianValueToAdd) > 0:
            self.toDo["median"].append({"targets": medianValueToAdd, "prefix": "BSMED"})
          self.toDo[tag].append({"targets": set(targets), "prefix": prefix, "threshold": threshold})
        elif tag in ["expectedShortfall", "valueAtRisk"]:
          # get targets
          targets = set(child.value)
          if tag not in self.toDo.keys():
            self.toDo[tag] = [] # list of {"targets": (), "prefix": str, "threshold": str}
            if "threshold" not in child.parameterValues:
              threshold = 0.05
            else:
              threshold = child.parameterValues["threshold"]
              if threshold > 1 or threshold < 0:
                self.raiseAnError("Threshold in {}, prefix '{}' out of range, please use a float in range (0, 1)!".format(tag, prefix))
            # cast threshold to set
            try:
              thresholdSet = set(threshold)
            except TypeError:
              # not iterable, must be float or int
              thresholdSet = set([threshold])
            strThreshold = set()
            for val in thresholdSet:
              strThreshold.add(str(val))
            self.toDo[tag].append({"targets": set(targets),
                                   "prefix": prefix,
                                   "threshold": thresholdSet,
                                   "strThreshold": strThreshold})
        else:
          if tag not in self.toDo.keys():
            self.toDo[tag] = [] # list of {"targets": (), "prefix": str}
          if "expectedValue" not in self.toDo.keys():
            self.toDo["expectedValue"] = []
          if "sigma" not in self.toDo.keys():
            self.toDo["sigma"] = []
          # add any expectedValue targets that are missing
          expectedValueToAdd = self._additionalTargetsToAdd("expectedValue", child.value)
          if len(expectedValueToAdd) > 0:
            self.toDo["expectedValue"].append({"targets": expectedValueToAdd, "prefix": "BSMean"})
          # add any sigma targets that are missing
          sigmaToAdd = self._additionalTargetsToAdd("sigma", child.value)
          if len(sigmaToAdd) > 0:
            self.toDo["sigma"].append({"targets": sigmaToAdd, "prefix": "BSSigma"})
          self.toDo[tag].append({"targets": set(child.value), "prefix": prefix})
      else:
        if tag not in self.scalarVals + self.vectorVals:
          self.raiseAWarning("Unrecognized node in EconomicRatio '" + tag + "' has been ignored!")

    assert(len(self.toDo) > 0), self.raiseAnError(IOError, "EconomicRatio needs parameters to work on! please check input for PP: " + self.name)

  def _additionalTargetsToAdd(self, metric, childValue):
    """
      Some EconomicRatio metrics require additional metrics from BasicStatistics, find necessary additions
      @ In, metric, str, name of metric
      @ In, childValue, set, set of targets
      @ Out, valsToAdd, set, set of targets to add to toDo
    """

    if len(self.toDo[metric]) > 0:
      # check if metric should be added
      vals = set() # currently collected
      for tmp_dict in self.toDo[metric]:
        if len(vals) == 0:
          vals = set(tmp_dict["targets"])
        else:
          vals = vals.union(tmp_dict["targets"])
      valsToAdd = set()
      for val in childValue:
        if val not in vals:
          valsToAdd.add(val)
    else:
      valsToAdd = set(childValue)

    return valsToAdd

  def _computeSortedWeightsAndPoints(self,arrayIn,pbWeight,percent):
    """
      Method to compute the sorted weights and points
      @ In, arrayIn, list/numpy.array, the array of values from which the percentile needs to be estimated
      @ In, pbWeight, list/numpy.array, the reliability weights that correspond to the values in 'array'
      @ In, percent, float, the percentile that needs to be computed (between 0.01 and 1.0)
      @ Out, sortedWeightsAndPoints, list/numpy.array, with [:,0] as the value of the probability density function at the bin, normalized, and [:,1] is the coresonding edge of the probability density function.
      @ Out, indexL, index of the lower quantile
    """

    idxs                   = np.argsort(np.asarray(list(zip(pbWeight,arrayIn)))[:,1])
    sortedWeightsAndPoints = np.asarray(list(zip(pbWeight[idxs],arrayIn[idxs])))
    weightsCDF             = np.cumsum(sortedWeightsAndPoints[:,0])
    indexL = utils.first(np.asarray(weightsCDF >= percent).nonzero())[0]
    return sortedWeightsAndPoints, indexL

  def __runLocal(self, inputData):
    """
      This method executes the postprocessor action. In this case, it computes all the requested statistical FOMs
      @ In, inputData, tuple,  (inputDataset, pbWeights), tuple, the dataset of inputs and the corresponding
        variable probability weight
      @ Out, outputSet or outputDict, xarray.Dataset or dict, dataset or dictionary containing the results
    """
    inputDataset, pbWeights = inputData[0], inputData[1]
    #storage dictionary for skipped metrics
    self.skipped = {}
    #construct a dict of required computations
    needed = dict((metric,{'targets':set()}) for metric in self.scalarVals + self.econVals)
    needed.update(dict((metric,{'targets':set(),'threshold':{}}) for metric in ['sortinoRatio','gainLossRatio']))
    needed.update(dict((metric,{'targets':set(),'threshold':set()}) for metric in ['valueAtRisk', 'expectedShortfall']))
    for metric, params in self.toDo.items():
      if metric in self.vectorVals:
        # vectorVals handled in BasicStatistics, not here
        continue
      for entry in params:
        needed[metric]['targets'].update(entry['targets'])
        if 'threshold' in entry.keys() :
          if metric in ['sortinoRatio','gainLossRatio']:
            threshold = entry['threshold']
            for k in entry['targets']:
              if k in needed[metric]['threshold'].keys():
                needed[metric]['threshold'][k].append(entry['threshold'])
              else:
                needed[metric]['threshold'][k] = []
                needed[metric]['threshold'][k].append(entry['threshold'])
          else:
            thd = entry['threshold']
            if thd not in needed[metric]['threshold']:
              needed[metric]['threshold'].update(thd)

    # variable                     | needs                  | needed for
    # --------------------------------------------------------------------
    # median needs                 |                        | sortinoRatio, gainLossRatio
    # sigma needs                  | variance               | sharpeRatio
    # variance                     | expectedValue          | sigma
    # expectedValue                |                        | sharpeRatio, sortinoRatio, gainLossRatio
    # sharpeRatio needs            | expectedValue,sigma    |
    # sortinoRatio needs           | expectedValue,median   |
    # gainLossRatio needs          | expectedValue,median   |

    # update needed dictionary when standard errors are requested
    needed['expectedValue']['targets'].update(needed['sigma']['targets'])
    needed['expectedValue']['targets'].update(needed['variance']['targets'])
    needed['expectedValue']['targets'].update(needed['median']['targets'])
    needed['expectedValue']['targets'].update(needed['sharpeRatio']['targets'])
    needed['expectedValue']['targets'].update(needed['sortinoRatio']['targets'])
    needed['expectedValue']['targets'].update(needed['gainLossRatio']['targets'])
    needed['sigma']['targets'].update(needed['sharpeRatio']['targets'])
    needed['variance']['targets'].update(needed['sigma']['targets'])
    needed['median']['targets'].update(needed['sortinoRatio']['targets'])
    needed['median']['targets'].update(needed['gainLossRatio']['targets'])

    for metric, params in needed.items():
      needed[metric]['targets'] = list(params['targets'])

    #
    # BEGIN actual calculations
    #

    calculations = self.calculations

    #################
    # ECON VALUES   #
    #################
    #
    # SharpeRatio
    #
    metric = 'sharpeRatio'
    if len(needed[metric]['targets'])>0:
      self.raiseADebug('Starting "'+metric+'"...')
      meanSet = calculations['expectedValue'][list(needed[metric]['targets'])]
      sigmaSet = calculations['sigma'][list(needed[metric]['targets'])]
      relWeight = pbWeights[list(needed[metric]['targets'])] if self.pbPresent else None
      calculations[metric] = meanSet/sigmaSet
    #
    # ValueAtRisk
    #
    metric = 'valueAtRisk'
    if len(needed[metric]['targets'])>0:
      self.raiseADebug('Starting "'+metric+'"...')
      dataSet = inputDataset[list(needed[metric]['targets'])]
      threshold = list(needed[metric]['threshold'])
      VaRSet = xr.Dataset()
      relWeight = pbWeights[list(needed[metric]['targets'])]
      targWarn = "" # targets that return negative VaR for warning
      for target in needed[metric]['targets']:
        targWeight = relWeight[target].values
        targDa = dataSet[target]
        VaRList = []
        for thd in threshold:
          if self.pivotParameter in targDa.sizes.keys():
            VaR = [-self._computeWeightedPercentile(group.values,targWeight,percent=thd) for label,group in targDa.groupby(self.pivotParameter)]
          else:
            VaR = -self._computeWeightedPercentile(targDa.values,targWeight,percent=thd)
          VaRList.append(VaR)
        if np.any(np.array(VaRList) < 0):
          targWarn += target + ", "
        if self.pivotParameter in targDa.sizes.keys():
          da = xr.DataArray(VaRList,dims=('threshold',self.pivotParameter),coords={'threshold':threshold,self.pivotParameter:self.pivotValue})
        else:
          da = xr.DataArray(VaRList,dims=('threshold'),coords={'threshold':threshold})
        VaRSet[target] = da
      # write warning for negative VaR values
      if len(targWarn) > 0:
        self.raiseAWarning("At least one negative VaR value calculated for target(s) {}. Negative VaR implies high probability of profit.".format(targWarn[:-2]))
      calculations[metric] = VaRSet

      # calculate value at risk standard error here
      # Reference for percentile standard error calculation:
      # B. Harding, C. Tremblay and D. Cousineau, "Standard errors: A review and evaluation of
      # standard error estimators using Monte Carlo simulations", The Quantitative Methods of
      # Psychology, Vol. 10, No. 2 (2014)
      self.raiseADebug('Starting "'+metric+'" standard error...')
      VaRSteSet = xr.Dataset()
      calculatedVaR = calculations[metric]
      relWeight = pbWeights[list(needed[metric]['targets'])]
      for target in needed[metric]['targets']:
        targWeight = relWeight[target].values
        en = targWeight.sum()**2/np.sum(targWeight**2)
        targDa = dataSet[target]
        if self.pivotParameter in targDa.sizes.keys():
          VaRSte = []
          for thd in threshold:
            subVaRSte = []
            factor = np.sqrt(thd*(1.0 - thd)/en)
            for label, group in targDa.groupby(self.pivotParameter):
              if group.values.min() == group.values.max():
                # all values are the same
                subVaRSte.append(0.0)
              else:
                # get KDE
                kde = stats.gaussian_kde(group.values, weights=targWeight)
                val = calculatedVaR[target].sel(**{'threshold': thd, self.pivotParameter: label}).values
                subVaRSte.append(factor/kde(val)[0])
            VaRSte.append(subVaRSte)
          da = xr.DataArray(VaRSte, dims=('threshold', self.pivotParameter),
                            coords={'threshold': threshold, self.pivotParameter: self.pivotValue})
          VaRSteSet[target] = da
        else:
          calcVaR = calculatedVaR[target]
          if targDa.values.min() == targDa.values.max():
            # distribution is a delta function, so no KDE construction
            VaRSte = list(np.zeros(calcVaR.shape))
          else:
            # get KDE
            kde = stats.gaussian_kde(targDa.values, weights=targWeight)
            factor = np.sqrt(np.array(threshold)*(1.0 - np.array(threshold))/en)
            VaRSte = list(factor/kde(calcVaR.values))
          da = xr.DataArray(VaRSte, dims=('threshold'), coords={'threshold': threshold})
          VaRSteSet[target] = da
      calculations[metric+'_ste'] = VaRSteSet
    #
    # ExpectedShortfall
    #
    metric = 'expectedShortfall'
    if len(needed[metric]['targets'])>0:
      self.raiseADebug('Starting "'+metric+'"...')
      dataSet = inputDataset[list(needed[metric]['targets'])]
      threshold = list(needed[metric]['threshold'])
      CVaRSet = xr.Dataset()
      relWeight = pbWeights[list(needed[metric]['targets'])]
      for target in needed[metric]['targets']:
        targWeight = relWeight[target].values
        targDa = dataSet[target]
        CVaRList = []
        for thd in threshold:
          if self.pivotParameter in targDa.sizes.keys():
            subCVaR = []
            for label, group in targDa.groupby(self.pivotParameter):
              sortedWeightsAndPoints, indexL = self._computeSortedWeightsAndPoints(group.values, targWeight,thd)
              quantile = self._computeWeightedPercentile(group.values, targWeight, percent=thd)
              lowerPartialE = np.sum(sortedWeightsAndPoints[:indexL, 0]*sortedWeightsAndPoints[:indexL,1])
              lowerPartialP = np.sum(sortedWeightsAndPoints[:indexL,0])
              Es = lowerPartialE + quantile*(thd - lowerPartialP)
              subCVaR.append(-Es/(thd))
            CVaRList.append(subCVaR)
          else:
            sortedWeightsAndPoints, indexL = self._computeSortedWeightsAndPoints(targDa.values,targWeight,thd)
            quantile = self._computeWeightedPercentile(targDa.values,targWeight,percent=thd)
            lowerPartialE = np.sum(sortedWeightsAndPoints[:indexL,0]*sortedWeightsAndPoints[:indexL,1])
            lowerPartialP = np.sum(sortedWeightsAndPoints[:indexL,0])
            Es = lowerPartialE + quantile*(thd -lowerPartialP)
            CVaRList.append(-Es/(thd))
        if self.pivotParameter in targDa.sizes.keys():
          da = xr.DataArray(CVaRList,dims=('threshold',self.pivotParameter),coords={'threshold':threshold,self.pivotParameter:self.pivotValue})
        else:
          da = xr.DataArray(CVaRList,dims=('threshold'),coords={'threshold':threshold})
        CVaRSet[target] = da
      calculations[metric] = CVaRSet
    #
    # sortinoRatio
    #
    metric = 'sortinoRatio'
    if len(needed[metric]['targets'])>0:
      self.raiseADebug('Starting "'+metric+'"...')
      meanSet = calculations['expectedValue'][list(needed[metric]['targets'])]
      relWeight = pbWeights[list(needed[metric]['targets'])]
      orgZeroSet = xr.full_like(meanSet, 0)
      orgMedSet = calculations['median']
      zeroTarget = []
      daZero = xr.Dataset()
      medTarget = []
      daMed = xr.Dataset()
      for entry in self.toDo[metric]:
        if entry['threshold'] == 'zero':
          zeroTarget = entry['targets']
          zeroSet = orgZeroSet[list(zeroTarget)]
          dataSet = inputDataset[list(zeroTarget)]
          lowerPartialVarianceDS = self._computeLowerPartialVariance(dataSet,zeroSet,pbWeight=relWeight,dim=self.sampleTag)
          lpsDS = self._computePower(0.5,lowerPartialVarianceDS)
          incapableZeroTarget = [x for x in zeroTarget if not lpsDS[x].values != 0]
          for target in incapableZeroTarget:
            needed[metric]['threshold'][target].remove('zero')
          zeroTarget = [x for x in zeroTarget if not lpsDS[x].values == 0]
          if incapableZeroTarget:
            self.raiseAWarning("For metric {} target {}, no lower part data can be found for threshold zero!  Skipping target".format(metric, incapableZeroTarget))
          daZero = meanSet[zeroTarget]/lpsDS[zeroTarget]
          daZero = daZero.assign_coords(threshold ='zero')
          daZero = daZero.expand_dims('threshold')
        elif entry['threshold'] == 'median':
          medTarget = entry['targets']
          medSet = orgMedSet[list(medTarget)]
          dataSet = inputDataset[list(medTarget)]
          lowerPartialVarianceDS = self._computeLowerPartialVariance(dataSet,medSet,pbWeight=relWeight,dim=self.sampleTag)
          lpsDS = self._computePower(0.5,lowerPartialVarianceDS)
          incapableMedTarget = [x for x in medTarget if not lpsDS[x].values != 0]
          medTarget = [x for x in medTarget if not lpsDS[x].values == 0]
          if incapableMedTarget:
            self.raiseAWarning("For metric {} target {}, no lower part data can be found for threshold median!  Skipping target".format(metric, incapableMedTarget))

          daMed = meanSet[medTarget]/lpsDS[medTarget]
          daMed = daMed.assign_coords(threshold ='median')
          daMed = daMed.expand_dims('threshold')
      calculations[metric] = xr.merge([daMed, daZero])
    #
    # gainLossRatio
    #
    metric = 'gainLossRatio'
    if len(needed[metric]['targets'])>0:
      self.raiseADebug('Starting "'+metric+'"...')
      relWeight = pbWeights[list(needed[metric]['targets'])]
      orgMedSet = calculations['median']
      orgZeroSet = xr.full_like(orgMedSet, 0)
      zeroTarget = []
      daZero = xr.Dataset()
      medTarget = []
      daMed = xr.Dataset()

      for entry in self.toDo[metric]:
        if entry['threshold'] == 'zero':
          zeroTarget = entry['targets']
          zeroSet = orgZeroSet[list(zeroTarget)]
          dataSet = inputDataset[list(zeroTarget)]

          higherSet = (dataSet-zeroSet).clip(min=0)
          lowerSet = (zeroSet-dataSet).clip(min=0)
          relWeight = pbWeights[list(needed[metric]['targets'])] if self.pbPresent else None
          higherMeanSet = (higherSet * relWeight).sum(dim = self.sampleTag)
          lowerMeanSet = (lowerSet * relWeight).sum(dim = self.sampleTag)

          incapableZeroTarget = [x for x in zeroTarget if not lowerMeanSet[x].values != 0]
          for target in incapableZeroTarget:
            needed[metric]['threshold'][target].remove('zero')
          zeroTarget = [x for x in zeroTarget if not lowerMeanSet[x].values == 0]
          if incapableZeroTarget:
            self.raiseAWarning("For metric {} target {}, no lower part data can be found for threshold zero!  Skipping target".format(metric,incapableZeroTarget))
          daZero = higherMeanSet[zeroTarget]/lowerMeanSet[zeroTarget]
          daZero = daZero.assign_coords(threshold ='zero')
          daZero = daZero.expand_dims('threshold')

        elif entry['threshold'] == 'median':
          medTarget = entry['targets']
          medSet = orgMedSet[list(medTarget)]
          dataSet = inputDataset[list(medTarget)]

          higherSet = (dataSet-medSet).clip(min=0)
          lowerSet = (medSet-dataSet).clip(min=0)
          relWeight = pbWeights[list(needed[metric]['targets'])] if self.pbPresent else None
          higherMeanSet = (higherSet * relWeight).sum(dim = self.sampleTag)
          lowerMeanSet = (lowerSet * relWeight).sum(dim = self.sampleTag)

          incapableMedTarget = [x for x in medTarget if not lowerMeanSet[x].values != 0]
          medTarget = [x for x in medTarget if not lowerMeanSet[x].values == 0]
          if incapableMedTarget:
            self.raiseAWarning("For metric {} target {}, lower part mean is zero for threshold median!  Skipping target".format(metric, incapableMedTarget))

          daMed = higherMeanSet[medTarget]/lowerMeanSet[medTarget]
          daMed = daMed.assign_coords(threshold ='median')
          daMed = daMed.expand_dims('threshold')
      calculations[metric] = xr.merge([daMed, daZero])

    for metric, ds in calculations.items():
      if metric in self.scalarVals + self.steVals + self.econVals + ['equivalentSamples'] and metric !='samples':
        calculations[metric] = ds.to_array().rename({'variable':'targets'})
    outputSet = xr.Dataset(data_vars=calculations)

    if self.outputDataset:
      # Add 'RAVEN_sample_ID' to output dataset for consistence
      if 'RAVEN_sample_ID' not in outputSet.sizes.keys():
        outputSet = outputSet.expand_dims('RAVEN_sample_ID')
        outputSet['RAVEN_sample_ID'] = [0]
      return outputSet
    else:
      outputDict = {}
      for metric, requestList  in self.toDo.items():
        for targetDict in requestList:
          prefix = targetDict['prefix'].strip()
          for target in targetDict['targets']:
            if metric in self.econVals:
              if metric in ['sortinoRatio','gainLossRatio']:
                varName = prefix + '_' + targetDict['threshold'] + '_' + target
                outputDict[varName] = np.atleast_1d(outputSet[metric].sel(**{'targets':target,'threshold':targetDict['threshold']}))
              elif metric in ['valueAtRisk','expectedShortfall']:
                for thd in targetDict['strThreshold']:
                  varName = '_'.join([prefix,thd,target])
                  thdVal = float(thd)
                  outputDict[varName] = np.atleast_1d(outputSet[metric].sel(**{'targets':target,'threshold':thdVal}))
                  steMetric = metric + '_ste'
                  if steMetric in self.steVals:
                    metaVar = '_'.join([prefix,thd,'ste',target])
                    outputDict[metaVar] = np.atleast_1d(outputSet[steMetric].sel(**{'targets':target,'threshold':thdVal}))
              else:
                varName = prefix + '_' + target
                outputDict[varName] = np.atleast_1d(outputSet[metric].sel(**{'targets':target}))
            else:
              #check if it was skipped for some reason
              skip = self.skipped.get(metric, None)
              if skip is not None:
                self.raiseADebug('Metric',metric,'was skipped for parameters',targetDict,'!  See warnings for details.  Ignoring...')
                continue
      if self.pivotParameter in outputSet.sizes.keys():
        outputDict[self.pivotParameter] = np.atleast_1d(self.pivotValue)

      return outputDict

  def run(self, inputIn):
    """
      This method executes the postprocessor action. In this case, it computes all the requested statistical FOMs
      @ In,  inputIn, object, object contained the data to process. (inputToInternal output)
      @ Out, outputSet, xarray.Dataset or dictionary, dataset or dictionary containing the results
    """
    # get metrics from BasicStatistics
    outputSetBasicStatistics = BasicStatistics.run(self, inputIn)

    # get metrics from EconomicRatio
    inputData = self.inputToInternal(inputIn)
    outputSet = self.__runLocal(inputData)

    # combine results
    if isinstance(outputSet, dict):
      if isinstance(outputSetBasicStatistics, dict):
        # BasicStatistics and EconomicRatio returned dictionaries
        outputSet.update(outputSetBasicStatistics)
      else:
        # BasicStatistics returned a xr.Dataset, EconomicRatio returned dict (empty)
        outputSet = outputSetBasicStatistics
    else:
      if isinstance(outputSetBasicStatistics, dict):
        # EconomicRatio returned xarray.Dataset, but BasicStatistics was dict (empty)
        pass
      else:
        # Both BasicStatistics and EconomicRatio returned xarray.Datasets
        outputSet = xr.merge([outputSet, outputSetBasicStatistics])

    return outputSet
