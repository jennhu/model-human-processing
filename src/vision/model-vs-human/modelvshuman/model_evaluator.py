import copy
import datetime
import logging
import os

import torch
import numpy as np

from tqdm import tqdm

from dataclasses import field

from .datasets import ToTensorflow
from .evaluation import evaluate as e
from .evaluation import metrics as m

from .utils import load_dataset, load_model

logger = logging.getLogger(__name__)
MAX_NUM_MODELS_IN_CACHE = 3


def device():
    return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


class ModelEvaluator:

    def _pytorch_evaluator(self, model_name, model, dataset, *args, **kwargs):
        """
        Evaluate Model on the given dataset and return the accuracy.
        Args:
            model_name:
            model:
            dataset:
            *args:
            **kwargs:
        """

        logging_info = f"Evaluating model {model_name} on dataset {dataset.name} using Pytorch Evaluator"
        logger.info(logging_info)
        print(logging_info)
        for metric in dataset.metrics:
            metric.reset()
        with torch.no_grad():
            result_writer = e.ResultPrinter(model_name=model_name,
                                            dataset=dataset)

            for images, target, paths in tqdm(dataset.loader):
                images = images.to(device())
                logits = model.forward_batch(images)
                softmax_output = model.softmax(logits)
                if isinstance(target, torch.Tensor):
                    batch_targets = model.to_numpy(target)
                else:
                    batch_targets = target
                predictions = dataset.decision_mapping(softmax_output)
                for metric in dataset.metrics:
                    metric.update(predictions,
                                  batch_targets,
                                  paths)
                if kwargs["print_predictions"]:
                    result_writer.print_batch_to_csv(object_response=predictions,
                                                     batch_targets=batch_targets,
                                                     paths=paths)

    def _tensorflow_evaluator(self, model_name, model, dataset, *args, **kwargs):
        """
        Evaluate Model on the given dataset and return the accuracy.
        Args:
            model_name:
            model:
            dataset:
            *args:
            **kwargs:

        Returns:
            accuracy
        """

        logging_info = f"Evaluation model {model_name} on dataset {dataset.name} using Tensorflow Evaluator"
        logger.info(logging_info)
        print(logging_info)
        result_writer = e.ResultPrinter(model_name=model_name,
                                        dataset=dataset)
        for metric in dataset.metrics:
            metric.reset()
        for images, target, paths in tqdm(dataset.loader):
            logits = model.forward_batch(images)
            softmax_output = model.softmax(logits)
            predictions = dataset.decision_mapping(softmax_output)
            for metric in dataset.metrics:
                metric.update(predictions,
                              target,
                              paths)
            if kwargs["print_predictions"]:
                result_writer.print_batch_to_csv(object_response=predictions,
                                                 batch_targets=target,
                                                 paths=paths)

    def _get_datasets(self, dataset_names, *args, **kwargs):
        dataset_list = []
        for dataset in dataset_names:
            dataset = load_dataset(dataset, *args, **kwargs)
            dataset_list.append(dataset)
        return dataset_list

    def _to_tensorflow(self, datasets):
        datasets = copy.deepcopy(datasets)
        new_datasets = []
        for dataset in datasets:
            dataset.loader = ToTensorflow(dataset.loader)
            new_datasets.append(dataset)
        return new_datasets

    def _get_evaluator(self, framework):
        if framework == "tensorflow":
            return self._tensorflow_evaluator
        elif framework == 'pytorch':
            return self._pytorch_evaluator
        else:
            raise NameError("Unsupported evaluator")

    def _remove_model_from_cache(self, framework, model_name):

        def _format_name(name):
            return name.lower().replace("-", "_")

        try:
            if framework == "pytorch":
                cachedir = "/root/.cache/torch/checkpoints/"
                downloaded_models = os.listdir(cachedir)
                for dm in downloaded_models:
                    if _format_name(dm).startswith(_format_name(model_name)):
                        os.remove(os.path.join(cachedir, dm))
        except:
            pass

    def __call__(self, models, dataset_names, *args, **kwargs):
        """
        Wrapper call to _evaluate function.

        Args:
            models:
            dataset_names:
            *args:
            **kwargs:

        Returns:

        """
        logging.info("Model evaluation.")
        _datasets = self._get_datasets(dataset_names, *args, **kwargs)
        for model_name in models:
            datasets = _datasets
            model, framework = load_model(model_name, *args)
            evaluator = self._get_evaluator(framework)
            if framework == 'tensorflow':
                datasets = self._to_tensorflow(datasets)
            logger.info(f"Loaded model: {model_name}")
            for dataset in datasets:
                # start time
                time_a = datetime.datetime.now()
                evaluator(model_name, model, dataset, *args, **kwargs)
                for metric in dataset.metrics:
                    logger.info(str(metric))
                    print(metric)

                # end time
                time_b = datetime.datetime.now()
                c = time_b - time_a

                if kwargs["print_predictions"]:
                    # print performances to csv
                    for metric in dataset.metrics:
                        e.print_performance_to_csv(model_name=model_name,
                                                   dataset_name=dataset.name,
                                                   performance=metric.value,
                                                   metric_name=metric.name)
            if len(models) >= MAX_NUM_MODELS_IN_CACHE:
                self._remove_model_from_cache(framework, model_name)

        logger.info("Finished evaluation.")


# @MLEPORI EDIT
class MetricExtractor:

 
    def _pytorch_extractor(self, model_name, model, dataset, *args, **kwargs):
        """
        Evaluate Model on the given dataset and return the accuracy.
        Args:
            model_name:
            model:
            dataset:
            *args:
            **kwargs:
        """

        logging_info = f"Extracting metrics using model {model_name} on dataset {dataset.name} using Pytorch Extractor"
        logger.info(logging_info)
        print(logging_info)

        # If swap out metrics and decision_mappings for metric purposes
        dataset.decision_mapping.__init__(return_raw_probs=True)
        dataset.metrics = [m.ReciprocalRank(), m.Probability(), m.Entropy()]

        with torch.no_grad():
            # result_writer = e.ResultPrinter(model_name=model_name,
            #                                 dataset=dataset)

            for images, target, paths in tqdm(dataset.loader):
                images = images.to(device())
                # Generate intermediate states
                final_feat, intermediates = model.model.forward_intermediates(images, norm=True, return_prefix_tokens=True)
                batch_size, hidden_size = final_feat.shape[0], final_feat.shape[2]
                
                # Iteratively compute Metrics over layers
                for layer, intermediate_features in enumerate(intermediates):
                    # Reshape intermediate outputs to match final
                    spatial_intermediates = intermediate_features[0]
                    prefix_intermediates = intermediate_features[1]
                    spatial_intermediates = spatial_intermediates.reshape(batch_size, -1, hidden_size)

                    intermediate_features = torch.cat([prefix_intermediates, spatial_intermediates], dim=1)
                    predictions = model.model.forward_head(intermediate_features)
                    predictions = model.softmax(predictions.cpu().numpy())

                    if isinstance(target, torch.Tensor):
                        batch_targets = model.to_numpy(target)
                    else:
                        batch_targets = target

                    # For each layer, get a probability distribution over relevant categories
                    predictions, categories = dataset.decision_mapping(predictions)

                    # Compute each metric and store it at the stimulus (x layer) level of granularity
                    for metric in dataset.metrics:
                        metric.update(predictions,
                                      categories,
                                      batch_targets,
                                      paths,
                                      layer)
                                
                # if kwargs["print_predictions"]:
                #     result_writer.print_batch_to_csv(object_response=predictions,
                #                                      batch_targets=batch_targets,
                #                                      paths=paths)

    def _get_datasets(self, dataset_names, *args, **kwargs):
        dataset_list = []
        for dataset in dataset_names:
            dataset = load_dataset(dataset, *args, **kwargs)
            dataset_list.append(dataset)
        return dataset_list

    def _get_extractor(self, framework):
        if framework == "tensorflow":
            raise ValueError("Tensorflow is not supported")
        elif framework == 'pytorch':
            return self._pytorch_extractor
        else:
            raise NameError("Unsupported extractor")

    def _remove_model_from_cache(self, framework, model_name):

        def _format_name(name):
            return name.lower().replace("-", "_")

        try:
            if framework == "pytorch":
                cachedir = "/root/.cache/torch/checkpoints/"
                downloaded_models = os.listdir(cachedir)
                for dm in downloaded_models:
                    if _format_name(dm).startswith(_format_name(model_name)):
                        os.remove(os.path.join(cachedir, dm))
        except:
            pass

    def __call__(self, models, dataset_names, *args, **kwargs):
        """
        Wrapper call to _evaluate function.

        Args:
            models:
            dataset_names:
            *args:
            **kwargs:

        Returns:

        """
        logging.info("Model evaluation.")
        _datasets = self._get_datasets(dataset_names, *args, **kwargs)
        for model_name in models:
            datasets = _datasets
            model, framework = load_model(model_name, *args)
            extractor = self._get_extractor(framework)
            if framework == 'tensorflow':
                raise ValueError("Tensorflow models not supported")
            logger.info(f"Loaded model: {model_name}")
            for dataset_idx, dataset in enumerate(datasets):
                print(dataset_names[dataset_idx])

                # start time
                time_a = datetime.datetime.now()
                extractor(model_name, model, dataset, *args, **kwargs)
                for metric in dataset.metrics:
                    logger.info(str(metric))

                # end time
                time_b = datetime.datetime.now()
                c = time_b - time_a

                if kwargs["print_predictions"]:
                    # print performances to csv
                    for metric in dataset.metrics:
                        e.print_metrics_to_csv(model_name=model_name,
                                                   dataset_name=dataset.name,
                                                   metric_dict=metric.value,
                                                   metric_name=metric.name)
            if len(models) >= MAX_NUM_MODELS_IN_CACHE:
                self._remove_model_from_cache(framework, model_name)

        logger.info("Finished evaluation.")

        # 3) Try to run this on a dataset