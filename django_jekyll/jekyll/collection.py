from django.utils.text import slugify
from django_jekyll import config, exceptions
from django_jekyll.jekyll.doc import Document
import re
import logging

logger = logging.getLogger(__name__)


class Collection(object):
    """ a Jekyll Collection."""
    @property
    def docs(self):
        """ generate the documents to be written out
        :return: `generator` of `docs.Document` to be written out
        """
        counter = 0

        while True:
            batch = list(self.queryset()[counter:counter + config.JEKYLL_MAX_BATCH_SIZE])

            if counter + len(batch) > config.JEKYLL_MAX_COLLECTION_SIZE:
                raise exceptions.CollectionSizeExceeded("%s exceeded size constraint of %s (has %s)!" % (self, config.JEKYLL_MAX_COLLECTION_SIZE, counter + len(batch)))
            elif len(batch) == 0:
                return

            parsed = self.parse_to_docs(batch)

            for p in parsed:
                yield p

            counter += config.JEKYLL_MAX_BATCH_SIZE

    def queryset(self):
        """ base queryset of models to generate collection from.
        :return:
        """
        return self.model.objects.all()

    def parse_to_docs(self, models):
        """ parse the given list of Models to Document instances
        :param models:
        :return:
        """
        return map(self.parse_to_document, models)

    def parse_to_document(self, model):
        field_val_map = {}
        field_meta_map = {}

        for f in model._meta.get_fields(include_hidden=True):
            if f.name in self.fields:
                field_meta_map[f.name] = f
            elif f.related_model:
                # if the field is a related model field AND we have a related lookup field in our self.fields (like 'client__name')
                for meta_field in self.fields:
                    field_parts = self._related_lookup_parts(meta_field)

                    if field_parts and field_parts[0] == f.name:
                        field_meta_map[meta_field] = f

        # check that all required fields are present, raising errors if not
        if self.content_field not in field_meta_map:
            raise exceptions.DocGenerationFailure("content_field %s wasn't found on model %s" % (self.content_field, model))
        elif type(self.filename_field) is str and self.filename_field not in field_meta_map:
            raise exceptions.DocGenerationFailure("filename_field %s is a string and wasn't found on model %s, either make it a function or use a different field" % (self.filename_field, model))

        # for each field, run it through a field parser to get the value of the field
        for fname, fmeta in field_meta_map.items():
            field_val = self.parse_field(model, fname, fmeta)

            field_parts = self._related_lookup_parts(fname)

            if fmeta.related_model and field_parts:
                field_val_map[field_parts[1]] = field_val
            else:
                field_val_map[fname] = field_val

        return Document(field_val_map[self.content_field],
                        filename=field_val_map[self.filename_field] if type(self.filename_field) is str else self.filename_field(model),
                        frontmatter_data=field_val_map)

    def parse_field(self, model, field_name, field_meta):
        """ given a model, a field name (can include lookups like 'client__name', 'client__goal__name', etc.), and the
        field_meta object for the immediate field related to the field_name (so for simple case of 'name', this would
        be the 'name' field meta object, for the complex case of 'client__name', this would be the 'client' field meta
        object, and for 'client__goal__name', this would also be the 'client' field meta object), parse the value of the
        field given by field_name from the model and return it
        :param model:
        :param field_name:
        :param field_meta:
        :return:
        """
        pass

    ##-- Helpers --##
    def _related_lookup_parts(self, field_name):
        related_lookup_pattern = '^(\w(?:[0-9A-Za-z]|_[0-9A-Za-z])*)__\w.*'

        match = re.match(related_lookup_pattern, field_name)

        if match:
            immediate_field = match.groups()[0]

            tail_field_pattern = '.*__(\w(?:[0-9A-Za-z]|_[0-9A-Za-z])*)$'
            tail_field = re.match(tail_field_pattern, field_name).groups()[0]

            return immediate_field, tail_field

        return None

    ##-- Accessors --##
    @property
    def model(self):
        return self.Meta.model

    @property
    def fields(self):
        return self.Meta.fields

    @property
    def content_field(self):
        return self.Meta.content_field

    @property
    def filename_field(self):
        return self.Meta.filename_field or str

    @property
    def jekyll_label(self):
        return self.Meta.jekyll_label or slugify(self.model.__name__).replace('-', '_')

    def __str__(self):
        return 'Collection (%s -> %s)' % (self.model.__name__, self.jekyll_label)

    class Meta:
        model = None
        fields = []
        # the name of the field on the model containing the data to be used as the content of the documents
        content_field = 'text'
        # the name of a field or a function to be used to set the filenames on the documents of the collection
        filename_field = None
        jekyll_label = None


def discover_collections():
    """ search through the projects installed apps, for each looking for the presence of a jekyll.py file (or whatever
    the overriden name is in config.JEKYLL_COLLECTIONS_FILENAME)
    :return: `generator` of `Collection` discovered in each of the collection files found
    """
    pass


def atomic_write_collection(collection, location):
    """ given a collection, atomically write the collections' data to location. Meaning, if any document in the collection
    fails to generate/write, the entire operation aborts
    :param collection:
    :return:
    """
    counter = 0

    try:
        for doc in collection.docs:
            doc.write(location)
    except (exceptions.DocGenerationFailure, exceptions.CollectionSizeExceeded) as exc:
        logger.error('atomic write failed! (%s)' % str(exc))

